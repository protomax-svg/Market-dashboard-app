"""
Standalone 3D Surface window: Time × Timeframe × Metric (ER / VOV).
- Not a dock: independent QMainWindow, no layout state save/restore.
- DB reads only on main thread; worker receives pre-fetched candle data.
- QWebEngineView created only after window is shown; worker stopped before close.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QPushButton,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except Exception:
    QWebEngineView = None  # type: ignore
    _HAS_WEBENGINE = False

try:
    import plotly.graph_objects as go
    _HAS_PLOTLY = True
except Exception:
    go = None  # type: ignore
    _HAS_PLOTLY = False

from app.storage.db import Database, INTERVAL_MS
from app.ui.theme import STYLESHEET, TEXT, BG_MAIN


# ----------------------------
# Metric implementations (no DB)
# ----------------------------

def compute_efficiency_ratio(
    candles: List[Dict[str, Any]],
    window: int = 50,
) -> List[Tuple[int, float]]:
    if window < 2 or len(candles) < window + 1:
        return []
    closes = [float(c["close"]) for c in candles]
    times = [int(c["open_time"]) for c in candles]
    diffs = [0.0]
    for i in range(1, len(closes)):
        diffs.append(abs(closes[i] - closes[i - 1]))
    rolling = sum(diffs[1 : window + 1])
    out: List[Tuple[int, float]] = []
    for t in range(window, len(closes)):
        if t > window:
            rolling -= diffs[t - window + 1]
            rolling += diffs[t]
        net = abs(closes[t] - closes[t - window])
        er = (net / rolling) if rolling > 0 else 0.0
        out.append((times[t], er))
    return out


def compute_vol_of_vol(
    candles: List[Dict[str, Any]],
    vol_window: int = 20,
    vov_window: int = 30,
) -> List[Tuple[int, float]]:
    if vol_window < 2 or vov_window < 2:
        return []
    n = len(candles)
    if n < (vol_window + vov_window):
        return []

    def tr(curr: Dict[str, Any], prev_close: float) -> float:
        h = float(curr["high"])
        l = float(curr["low"])
        return max(h - l, abs(h - prev_close), abs(l - prev_close))

    trs: List[float] = [0.0] * n
    prev_close = float(candles[0].get("open", candles[0]["close"]))
    for i in range(n):
        trs[i] = tr(candles[i], prev_close)
        prev_close = float(candles[i]["close"])

    atr = sum(trs[:vol_window]) / vol_window
    atrs: List[Tuple[int, float]] = [(int(candles[vol_window - 1]["open_time"]), atr)]
    for i in range(vol_window, n):
        atr = ((atr * (vol_window - 1)) + trs[i]) / vol_window
        atrs.append((int(candles[i]["open_time"]), atr))

    out: List[Tuple[int, float]] = []
    buf: List[float] = []
    sum_a = 0.0
    sumsq = 0.0
    for t, a in atrs:
        buf.append(a)
        sum_a += a
        sumsq += a * a
        if len(buf) > vov_window:
            old = buf.pop(0)
            sum_a -= old
            sumsq -= old * old
        if len(buf) == vov_window:
            mean = sum_a / vov_window
            var = (sumsq / vov_window) - mean * mean
            vov = math.sqrt(var) if var > 0 else 0.0
            out.append((t, vov))
    return out


def zscore_series(points: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
    if not points:
        return []
    vals = [v for _, v in points]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals))
    std = math.sqrt(var) if var > 1e-12 else 1.0
    return [(t, (v - mean) / std) for t, v in points]


# ----------------------------
# Worker: receives pre-fetched data only (no DB access)
# ----------------------------

@dataclass
class SurfaceInput:
    """Pre-fetched candle data and options. No DB reference."""
    symbol: str
    timeframes: List[str]
    metric: str
    normalize: bool
    tf_candles: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


def build_surface_html_from_candles(inp: SurfaceInput) -> str:
    """Build Plotly HTML from pre-fetched candles. No DB access."""
    if not _HAS_PLOTLY or go is None:
        raise RuntimeError("plotly is not installed. pip install plotly")
    tf_series: Dict[str, List[Tuple[int, float]]] = {}

    for tf in inp.timeframes:
        candles = inp.tf_candles.get(tf, [])
        if inp.metric == "ER":
            pts = compute_efficiency_ratio(candles, window=50)
        elif inp.metric == "VOV":
            pts = compute_vol_of_vol(candles, vol_window=20, vov_window=30)
        else:
            pts = compute_efficiency_ratio(candles, window=50)
        if inp.normalize:
            pts = zscore_series(pts)
        tf_series[tf] = pts

    if not tf_series:
        raise ValueError("No series computed")

    base_tf = min(inp.timeframes, key=lambda x: INTERVAL_MS.get(x, 0))
    base_points = tf_series.get(base_tf, [])
    if len(base_points) < 3:
        raise ValueError("Not enough data in selected range for surface")

    x_times = [t for t, _ in base_points]
    y_tfs = inp.timeframes[:]
    z: List[List[float]] = []

    for tf in y_tfs:
        pts = tf_series.get(tf, [])
        row: List[float] = []
        j = 0
        last_val: Optional[float] = None
        for xt in x_times:
            while j < len(pts) and pts[j][0] <= xt:
                last_val = pts[j][1]
                j += 1
            row.append(last_val if last_val is not None else float("nan"))
        z.append(row)

    x_labels = [time.strftime("%H:%M", time.gmtime(t / 1000)) for t in x_times]

    fig = go.Figure(
        data=[
            go.Surface(
                z=z,
                x=x_labels,
                y=y_tfs,
                showscale=True,
            )
        ]
    )
    fig.update_layout(
        title=f"3D Surface • {inp.symbol} • {inp.metric}{' (z)' if inp.normalize else ''}",
        scene=dict(
            xaxis_title="Time",
            yaxis_title="Timeframe",
            zaxis_title=inp.metric,
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        paper_bgcolor=BG_MAIN,
        plot_bgcolor=BG_MAIN,
        font=dict(color=TEXT),
    )
    return fig.to_html(include_plotlyjs="cdn", full_html=True)


class SurfaceWorker(QObject):
    surface_ready = Signal(str)
    error = Signal(str)

    def __init__(self, inp: SurfaceInput):
        super().__init__()
        self._inp = inp

    def run(self) -> None:
        try:
            html = build_surface_html_from_candles(self._inp)
            self.surface_ready.emit(html)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


# ----------------------------
# Standalone window
# ----------------------------

DEBOUNCE_MS = 400


class Surface3DWindow(QMainWindow):
    """
    Standalone 3D surface window. Not a dock.
    - QWebEngineView created only in showEvent (after window is shown).
    - DB reads happen on main thread; worker only receives pre-fetched data.
    - closeEvent stops worker before closing; no deleteLater on view while active.
    """

    def __init__(
        self,
        db: Database,
        symbol: str = "BTCUSDT",
        lookback_hours: int = 24,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Vol Stability (3D)")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(640, 480)
        self.resize(900, 600)
        # Top-level window: movable, resizable, with title bar and min/max/close
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowState(Qt.WindowState.WindowNoState)

        self._db = db
        self._symbol = symbol
        self._lookback_hours = lookback_hours
        self._view: Optional[Any] = None  # QWebEngineView created in showEvent
        self._view_placeholder: Optional[QWidget] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[SurfaceWorker] = None
        self._debounce_timer: Optional[QTimer] = None
        self._closed = False

        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        controls = QHBoxLayout()
        layout.addLayout(controls)

        controls.addWidget(QLabel("Metric:"))
        self.metric_box = QComboBox()
        self.metric_box.addItems(["ER", "VOV"])
        controls.addWidget(self.metric_box)

        self.norm_box = QCheckBox("Normalize (z-score)")
        self.norm_box.setChecked(True)
        controls.addWidget(self.norm_box)

        controls.addWidget(QLabel("TFs:"))
        self.tf_5m = QCheckBox("5m")
        self.tf_5m.setChecked(True)
        self.tf_15m = QCheckBox("15m")
        self.tf_15m.setChecked(True)
        self.tf_1h = QCheckBox("1h")
        self.tf_1h.setChecked(True)
        for cb in (self.tf_5m, self.tf_15m, self.tf_1h):
            controls.addWidget(cb)

        self.refresh_btn = QPushButton("Refresh")
        controls.addWidget(self.refresh_btn)
        controls.addStretch(1)

        # Placeholder for view (replaced by QWebEngineView in showEvent)
        self._view_placeholder = QWidget()
        self._view_placeholder.setMinimumSize(400, 300)
        layout.addWidget(self._view_placeholder, 1)

        self.status = QLabel("")
        layout.addWidget(self.status)

        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.metric_box.currentIndexChanged.connect(self._schedule_refresh)
        self.norm_box.stateChanged.connect(self._schedule_refresh)
        for cb in (self.tf_5m, self.tf_15m, self.tf_1h):
            cb.stateChanged.connect(self._schedule_refresh)

        # No auto-run in __init__; start after show or on Refresh

    def _selected_timeframes(self) -> List[str]:
        tfs: List[str] = []
        if self.tf_5m.isChecked():
            tfs.append("5m")
        if self.tf_15m.isChecked():
            tfs.append("15m")
        if self.tf_1h.isChecked():
            tfs.append("1h")
        return tfs

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._view is None and _HAS_WEBENGINE and QWebEngineView is not None and self._view_placeholder is not None:
            self._view = QWebEngineView(self)
            layout = self.centralWidget().layout()
            if layout is not None:
                layout.replaceWidget(self._view_placeholder, self._view)
            self._view_placeholder.setParent(None)
            self._view_placeholder = None
            QTimer.singleShot(100, self._request_refresh)
        event.accept()

    def _schedule_refresh(self) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._request_refresh)
        self._debounce_timer.start(DEBOUNCE_MS)

    def _on_refresh_clicked(self) -> None:
        self._request_refresh()

    def _request_refresh(self) -> None:
        if self._closed:
            return
        if not _HAS_WEBENGINE or self._view is None:
            if self._view is None and not _HAS_WEBENGINE:
                self.status.setText("Install PySide6-WebEngine and plotly for 3D chart.")
            return

        self._stop_worker()

        # Fetch candles on main thread (no DB access from worker)
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - int(self._lookback_hours * 3600 * 1000)
        tfs = self._selected_timeframes()
        if not tfs:
            self.status.setText("Select at least one timeframe.")
            return

        tf_candles: Dict[str, List[Dict[str, Any]]] = {}
        for tf in tfs:
            candles = self._db.get_candles(self._symbol, tf, start_ms, end_ms)
            tf_candles[tf] = candles

        inp = SurfaceInput(
            symbol=self._symbol,
            timeframes=tfs,
            metric=str(self.metric_box.currentText()),
            normalize=bool(self.norm_box.isChecked()),
            tf_candles=tf_candles,
        )

        self.status.setText("Building surface…")
        self.refresh_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = SurfaceWorker(inp)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.surface_ready.connect(self._on_surface_ready)
        self._worker.error.connect(self._on_error)
        self._worker.surface_ready.connect(self._cleanup_worker)
        self._worker.error.connect(self._cleanup_worker)

        self._thread.start()

    def _stop_worker(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            # Short wait in close path to avoid blocking; worker has no DB/view refs
            self._thread.wait(300)
            self._thread = None
            self._worker = None

    def _cleanup_worker(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.refresh_btn.setEnabled(True)

    def _on_surface_ready(self, html: str) -> None:
        if self._closed or self._view is None:
            return
        self._view.setHtml(html)
        self.status.setText("")

    def _on_error(self, msg: str) -> None:
        self.status.setText(f"Error: {msg}")
        self.refresh_btn.setEnabled(True)

    def closeEvent(self, event) -> None:
        self._closed = True
        # Stop worker with short wait so we don't block the close path
        self._stop_worker()
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None
        # Detach QWebEngineView before the window is destroyed. Destroying the view
        # while the window is closing (same event path) causes crashes on Windows.
        # Remove from layout, orphan it, and deleteLater after a delay.
        if self._view is not None:
            layout = self.centralWidget().layout() if self.centralWidget() else None
            if layout is not None:
                layout.removeWidget(self._view)
            self._view.setParent(None)
            self._view.hide()
            view_to_delete = self._view
            self._view = None
            QTimer.singleShot(600, view_to_delete.deleteLater)
        super().closeEvent(event)

    def set_lookback_hours(self, hours: int) -> None:
        self._lookback_hours = hours
