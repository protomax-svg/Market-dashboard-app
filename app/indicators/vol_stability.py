# app/ui/surface3d_dock.py
"""
3D Surface dock widget: Time × Timeframe × Metric value.

- Renders an interactive Plotly 3D surface inside a QtWebEngineView.
- Computes multi-timeframe series from 1m candles stored in SQLite (Database).
- Runs heavy DB + compute work in a worker thread, then updates UI via Qt signals.

Drop this file into app/ui/, then in MainWindow create and add the dock:
    from app.ui.surface3d_dock import Surface3DSurfaceDock
    dock = Surface3DSurfaceDock(db=self.db, symbol=self.symbol)
    self.addDockWidget(Qt.RightDockWidgetArea, dock)

Requires:
    pip install plotly
    PySide6 with QtWebEngine (PySide6-WebEngine on some setups)
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox, QPushButton

try:
    # Depending on install, this can require PySide6-WebEngine
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except Exception:
    QWebEngineView = None  # type: ignore
    _HAS_WEBENGINE = False

import plotly.graph_objects as go

from app.storage.db import Database, INTERVAL_MS


# ----------------------------
# Metric implementations
# ----------------------------

def _log_return(c0: float, c1: float) -> float:
    if c0 <= 0 or c1 <= 0:
        return 0.0
    return math.log(c1 / c0)


def compute_efficiency_ratio(
    candles: List[Dict[str, Any]],
    window: int = 50,
) -> List[Tuple[int, float]]:
    """
    Kaufman Efficiency Ratio:
      ER = |price[t] - price[t-window]| / sum_{i=t-window+1..t} |price[i] - price[i-1]|
    Range: [0..1]
    """
    if window < 2 or len(candles) < window + 1:
        return []

    closes = [float(c["close"]) for c in candles]
    times = [int(c["open_time"]) for c in candles]

    out: List[Tuple[int, float]] = []
    # Precompute abs diffs
    diffs = [0.0]
    for i in range(1, len(closes)):
        diffs.append(abs(closes[i] - closes[i - 1]))

    # Rolling sum of diffs over "window"
    rolling = sum(diffs[1 : window + 1])
    for t in range(window, len(closes)):
        if t > window:
            # slide: remove diffs[t-window+1] add diffs[t]
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
    """
    Vol-of-Vol = rolling std of ATR (Wilder).
    Returns a series (timestamp, vov).
    """
    if vol_window < 2 or vov_window < 2:
        return []
    n = len(candles)
    if n < (vol_window + vov_window):
        return []

    def tr(curr: Dict[str, Any], prev_close: float) -> float:
        h = float(curr["high"]); l = float(curr["low"])
        return max(h - l, abs(h - prev_close), abs(l - prev_close))

    trs: List[float] = [0.0] * n
    prev_close = float(candles[0].get("open", candles[0]["close"]))
    for i in range(n):
        trs[i] = tr(candles[i], prev_close)
        prev_close = float(candles[i]["close"])

    # Wilder ATR init: SMA of first vol_window TRs
    atr = sum(trs[:vol_window]) / vol_window
    atrs: List[Tuple[int, float]] = [(int(candles[vol_window - 1]["open_time"]), atr)]
    for i in range(vol_window, n):
        atr = ((atr * (vol_window - 1)) + trs[i]) / vol_window
        atrs.append((int(candles[i]["open_time"]), atr))

    # Rolling std over ATRs
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
    """Global z-score normalization of values in the series."""
    if not points:
        return []
    vals = [v for _, v in points]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / max(1, len(vals))
    std = math.sqrt(var) if var > 1e-12 else 1.0
    return [(t, (v - mean) / std) for t, v in points]


# ----------------------------
# Worker thread
# ----------------------------

@dataclass
class SurfaceRequest:
    symbol: str
    start_ms: int
    end_ms: int
    timeframes: List[str]
    metric: str
    normalize: bool


class SurfaceWorker(QObject):
    surface_ready = Signal(str)   # HTML
    error = Signal(str)

    def __init__(self, db: Database, req: SurfaceRequest):
        super().__init__()
        self._db = db
        self._req = req

    def run(self) -> None:
        try:
            html = build_surface_html(self._db, self._req)
            self.surface_ready.emit(html)
        except Exception as e:
            self.error.emit(f"{type(e).__name__}: {e}")


def build_surface_html(db: Database, req: SurfaceRequest) -> str:
    """
    Build Plotly HTML for a surface:
      X: time index (common grid)
      Y: timeframe index
      Z: metric value (optionally z-scored per timeframe)
    """
    # 1) Pull / resample candles per timeframe
    tf_series: Dict[str, List[Tuple[int, float]]] = {}

    for tf in req.timeframes:
        if tf == "1m":
            candles = db.get_candles_1m(req.symbol, req.start_ms, req.end_ms)
        else:
            candles = db.resample_candles(req.symbol, req.start_ms, req.end_ms, tf)

        if req.metric == "ER":
            pts = compute_efficiency_ratio(candles, window=50)
        elif req.metric == "VOV":
            pts = compute_vol_of_vol(candles, vol_window=20, vov_window=30)
        else:
            # Default ER
            pts = compute_efficiency_ratio(candles, window=50)

        if req.normalize:
            pts = zscore_series(pts)

        tf_series[tf] = pts

    # 2) Choose common time grid:
    # Use the densest TF (1m if present, else smallest interval from list).
    # Then for each TF, map its points onto that grid via last-known (forward fill).
    if not tf_series:
        raise ValueError("No series computed")

    # Determine base tf
    base_tf = "1m" if "1m" in req.timeframes else min(req.timeframes, key=lambda x: INTERVAL_MS[x])
    base_points = tf_series.get(base_tf, [])
    if len(base_points) < 3:
        raise ValueError("Not enough data in selected range for surface")

    x_times = [t for t, _ in base_points]  # X axis = time grid (ms)

    # 3) Build Z matrix: rows = timeframes, cols = x_times
    y_tfs = req.timeframes[:]  # keep order
    z: List[List[float]] = []

    for tf in y_tfs:
        pts = tf_series.get(tf, [])
        # Build map pointer for forward-fill
        row: List[float] = []
        j = 0
        last_val: Optional[float] = None
        for xt in x_times:
            while j < len(pts) and pts[j][0] <= xt:
                last_val = pts[j][1]
                j += 1
            row.append(last_val if last_val is not None else float("nan"))
        z.append(row)

    # Make pretty x labels (HH:MM)
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
        title=f"3D Surface • {req.symbol} • {req.metric}{' (z)' if req.normalize else ''}",
        scene=dict(
            xaxis_title="Time",
            yaxis_title="Timeframe",
            zaxis_title=req.metric,
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        paper_bgcolor="#0f1115",
        plot_bgcolor="#0f1115",
        font=dict(color="#e5e7eb"),
    )
    # Full HTML (no external files)
    return fig.to_html(include_plotlyjs="cdn", full_html=True)


# ----------------------------
# Dock widget
# ----------------------------

class Surface3DSurfaceDock(QDockWidget):
    """
    Dockable widget that renders a 3D surface across multiple timeframes.
    """
    def __init__(self, db: Database, symbol: str = "BTCUSDT", parent: Optional[QWidget] = None):
        super().__init__("3D Surface", parent)
        self._db = db
        self._symbol = symbol

        root = QWidget(self)
        self.setWidget(root)
        layout = QVBoxLayout(root)

        # Controls
        controls = QHBoxLayout()
        layout.addLayout(controls)

        controls.addWidget(QLabel("Metric:"))
        self.metric_box = QComboBox()
        self.metric_box.addItems(["ER", "VOV"])  # extend later (Stress, PE, etc.)
        controls.addWidget(self.metric_box)

        self.norm_box = QCheckBox("Normalize (z-score)")
        self.norm_box.setChecked(True)
        controls.addWidget(self.norm_box)

        controls.addWidget(QLabel("TFs:"))
        self.tf_1m = QCheckBox("1m"); self.tf_1m.setChecked(True)
        self.tf_5m = QCheckBox("5m"); self.tf_5m.setChecked(True)
        self.tf_15m = QCheckBox("15m"); self.tf_15m.setChecked(True)
        self.tf_1h = QCheckBox("1h"); self.tf_1h.setChecked(True)
        controls.addWidget(self.tf_1m)
        controls.addWidget(self.tf_5m)
        controls.addWidget(self.tf_15m)
        controls.addWidget(self.tf_1h)

        self.refresh_btn = QPushButton("Refresh")
        controls.addWidget(self.refresh_btn)
        controls.addStretch(1)

        # View
        if _HAS_WEBENGINE:
            self.view = QWebEngineView()  # type: ignore[call-arg]
            layout.addWidget(self.view, 1)
        else:
            self.view = None
            layout.addWidget(QLabel("QtWebEngine is not installed. Install PySide6-WebEngine."))

        self.status = QLabel("")
        layout.addWidget(self.status)

        # Worker thread references
        self._thread: Optional[QThread] = None
        self._worker: Optional[SurfaceWorker] = None

        # Events
        self.refresh_btn.clicked.connect(self.refresh)
        self.metric_box.currentIndexChanged.connect(lambda _: self.refresh())
        self.norm_box.stateChanged.connect(lambda _: self.refresh())
        for cb in (self.tf_1m, self.tf_5m, self.tf_15m, self.tf_1h):
            cb.stateChanged.connect(lambda _: self.refresh())

        # Initial render
        self.refresh()

    def _selected_timeframes(self) -> List[str]:
        tfs: List[str] = []
        if self.tf_1m.isChecked(): tfs.append("1m")
        if self.tf_5m.isChecked(): tfs.append("5m")
        if self.tf_15m.isChecked(): tfs.append("15m")
        if self.tf_1h.isChecked(): tfs.append("1h")
        return tfs

    def refresh(self, lookback_hours: int = 24) -> None:
        """Rebuild surface for last N hours (wire this later to your global DateRange)."""
        if not _HAS_WEBENGINE or self.view is None:
            return

        # stop previous worker if running
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
            self._worker = None

        end_ms = int(time.time() * 1000)
        start_ms = end_ms - int(lookback_hours * 3600 * 1000)
        req = SurfaceRequest(
            symbol=self._symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            timeframes=self._selected_timeframes(),
            metric=str(self.metric_box.currentText()),
            normalize=bool(self.norm_box.isChecked()),
        )

        self.status.setText("Building surface…")
        self.refresh_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = SurfaceWorker(self._db, req)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.surface_ready.connect(self._on_surface_ready)
        self._worker.error.connect(self._on_error)
        self._worker.surface_ready.connect(lambda _: self._cleanup_worker())
        self._worker.error.connect(lambda _: self._cleanup_worker())

        self._thread.start()

    def _cleanup_worker(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self.refresh_btn.setEnabled(True)

    def _on_surface_ready(self, html: str) -> None:
        if self.view is None:
            return
        self.view.setHtml(html)
        self.status.setText("")

    def _on_error(self, msg: str) -> None:
        self.status.setText(f"Error: {msg}")
        self.refresh_btn.setEnabled(True)
