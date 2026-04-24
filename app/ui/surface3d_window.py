"""
Standalone 3D surface window for comparing metrics across time and timeframe.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
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
from app.ui.theme import BG_MAIN, STYLESHEET, TEXT


def compute_efficiency_ratio(
    candles: List[Dict[str, Any]],
    window: int = 50,
) -> List[Tuple[int, float]]:
    if window < 2 or len(candles) < window + 1:
        return []

    closes = [float(candle["close"]) for candle in candles]
    times = [int(candle["open_time"]) for candle in candles]
    diffs = [0.0]

    for index in range(1, len(closes)):
        diffs.append(abs(closes[index] - closes[index - 1]))

    rolling = sum(diffs[1 : window + 1])
    output: List[Tuple[int, float]] = []

    for index in range(window, len(closes)):
        if index > window:
            rolling -= diffs[index - window + 1]
            rolling += diffs[index]
        net = abs(closes[index] - closes[index - window])
        output.append((times[index], (net / rolling) if rolling > 0 else 0.0))

    return output


def compute_vol_of_vol(
    candles: List[Dict[str, Any]],
    vol_window: int = 20,
    vov_window: int = 30,
) -> List[Tuple[int, float]]:
    if vol_window < 2 or vov_window < 2:
        return []

    candle_count = len(candles)
    if candle_count < (vol_window + vov_window):
        return []

    def true_range(current: Dict[str, Any], prev_close: float) -> float:
        high = float(current["high"])
        low = float(current["low"])
        return max(high - low, abs(high - prev_close), abs(low - prev_close))

    trs: List[float] = [0.0] * candle_count
    prev_close = float(candles[0].get("open", candles[0]["close"]))
    for index in range(candle_count):
        trs[index] = true_range(candles[index], prev_close)
        prev_close = float(candles[index]["close"])

    atr = sum(trs[:vol_window]) / vol_window
    atrs: List[Tuple[int, float]] = [(int(candles[vol_window - 1]["open_time"]), atr)]
    for index in range(vol_window, candle_count):
        atr = ((atr * (vol_window - 1)) + trs[index]) / vol_window
        atrs.append((int(candles[index]["open_time"]), atr))

    output: List[Tuple[int, float]] = []
    buffer: List[float] = []
    sum_atr = 0.0
    sumsq = 0.0

    for timestamp, atr_value in atrs:
        buffer.append(atr_value)
        sum_atr += atr_value
        sumsq += atr_value * atr_value
        if len(buffer) > vov_window:
            old = buffer.pop(0)
            sum_atr -= old
            sumsq -= old * old
        if len(buffer) == vov_window:
            mean = sum_atr / vov_window
            variance = (sumsq / vov_window) - mean * mean
            output.append((timestamp, math.sqrt(variance) if variance > 0 else 0.0))

    return output


def zscore_series(points: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
    if not points:
        return []

    values = [value for _, value in points]
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
    std = math.sqrt(variance) if variance > 1e-12 else 1.0
    return [(timestamp, (value - mean) / std) for timestamp, value in points]


@dataclass
class SurfaceInput:
    symbol: str
    timeframes: List[str]
    metric: str
    normalize: bool
    tf_candles: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


def build_surface_html_from_candles(inp: SurfaceInput) -> str:
    if not _HAS_PLOTLY or go is None:
        raise RuntimeError("plotly is not installed. Install plotly to use the 3D view.")

    tf_series: Dict[str, List[Tuple[int, float]]] = {}
    for timeframe in inp.timeframes:
        candles = inp.tf_candles.get(timeframe, [])
        if inp.metric == "ER":
            points = compute_efficiency_ratio(candles, window=50)
        elif inp.metric == "VOV":
            points = compute_vol_of_vol(candles, vol_window=20, vov_window=30)
        else:
            points = compute_efficiency_ratio(candles, window=50)

        tf_series[timeframe] = zscore_series(points) if inp.normalize else points

    if not tf_series:
        raise ValueError("No series computed")

    base_tf = min(inp.timeframes, key=lambda value: INTERVAL_MS.get(value, 0))
    base_points = tf_series.get(base_tf, [])
    if len(base_points) < 3:
        raise ValueError("Not enough data in the selected range for a surface")

    x_times = [timestamp for timestamp, _ in base_points]
    y_tfs = inp.timeframes[:]
    z_values: List[List[float]] = []

    for timeframe in y_tfs:
        points = tf_series.get(timeframe, [])
        row: List[float] = []
        cursor = 0
        last_value: Optional[float] = None
        for x_time in x_times:
            while cursor < len(points) and points[cursor][0] <= x_time:
                last_value = points[cursor][1]
                cursor += 1
            row.append(last_value if last_value is not None else float("nan"))
        z_values.append(row)

    x_labels = [time.strftime("%H:%M", time.gmtime(timestamp / 1000)) for timestamp in x_times]

    fig = go.Figure(
        data=[
            go.Surface(
                z=z_values,
                x=x_labels,
                y=y_tfs,
                showscale=True,
            )
        ]
    )
    fig.update_layout(
        title=f"3D Surface | {inp.symbol} | {inp.metric}{' (z)' if inp.normalize else ''}",
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
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


DEBOUNCE_MS = 400


class Surface3DWindow(QMainWindow):
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
        self.resize(960, 640)
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
        self._view: Optional[Any] = None
        self._view_placeholder: Optional[QWidget] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[SurfaceWorker] = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._request_refresh)
        self._closed = False

        root = QWidget(self)
        root.setObjectName("SurfaceRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QFrame(self)
        header.setObjectName("ChartCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 16)
        header_layout.setSpacing(10)

        title = QLabel("Vol Stability Surface", header)
        title.setObjectName("ChartTitle")
        header_layout.addWidget(title)

        subtitle = QLabel(
            "Compare efficiency ratio and volatility-of-volatility across multiple timeframes.",
            header,
        )
        subtitle.setObjectName("ChartMeta")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        header_layout.addLayout(controls)

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
        for checkbox in (self.tf_5m, self.tf_15m, self.tf_1h):
            controls.addWidget(checkbox)

        self.refresh_btn = QPushButton("Refresh")
        controls.addWidget(self.refresh_btn)
        controls.addStretch(1)

        layout.addWidget(header)

        self._view_placeholder = QFrame(self)
        self._view_placeholder.setObjectName("ChartCard")
        placeholder_layout = QVBoxLayout(self._view_placeholder)
        placeholder_layout.setContentsMargins(18, 18, 18, 18)
        placeholder = QLabel(
            "The interactive surface will appear here after the window finishes loading.",
            self._view_placeholder,
        )
        placeholder.setObjectName("ChartStatus")
        placeholder.setWordWrap(True)
        placeholder_layout.addWidget(placeholder)
        placeholder_layout.addStretch(1)
        layout.addWidget(self._view_placeholder, 1)

        self.status = QLabel("Choose a metric and click Refresh.", self)
        self.status.setObjectName("ChartMeta")
        layout.addWidget(self.status)

        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.metric_box.currentIndexChanged.connect(self._schedule_refresh)
        self.norm_box.stateChanged.connect(self._schedule_refresh)
        for checkbox in (self.tf_5m, self.tf_15m, self.tf_1h):
            checkbox.stateChanged.connect(self._schedule_refresh)

    def _selected_timeframes(self) -> List[str]:
        timeframes: List[str] = []
        if self.tf_5m.isChecked():
            timeframes.append("5m")
        if self.tf_15m.isChecked():
            timeframes.append("15m")
        if self.tf_1h.isChecked():
            timeframes.append("1h")
        return timeframes

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if (
            self._view is None
            and _HAS_WEBENGINE
            and QWebEngineView is not None
            and self._view_placeholder is not None
        ):
            self._view = QWebEngineView(self)
            layout = self.centralWidget().layout() if self.centralWidget() is not None else None
            if layout is not None:
                layout.replaceWidget(self._view_placeholder, self._view)
            self._view_placeholder.setParent(None)
            self._view_placeholder = None
            QTimer.singleShot(100, self._request_refresh)

    def _schedule_refresh(self) -> None:
        self._debounce_timer.start(DEBOUNCE_MS)

    def _on_refresh_clicked(self) -> None:
        self._request_refresh()

    def _request_refresh(self) -> None:
        if self._closed:
            return

        if not _HAS_WEBENGINE or self._view is None:
            if not _HAS_WEBENGINE:
                self.status.setText("Install PySide6 and plotly to use the 3D chart.")
            return

        self._stop_worker()

        end_ms = int(time.time() * 1000)
        start_ms = end_ms - int(self._lookback_hours * 3600 * 1000)
        timeframes = self._selected_timeframes()
        if not timeframes:
            self.status.setText("Select at least one timeframe.")
            return

        tf_candles: Dict[str, List[Dict[str, Any]]] = {}
        for timeframe in timeframes:
            tf_candles[timeframe] = self._db.get_candles(self._symbol, timeframe, start_ms, end_ms)

        worker_input = SurfaceInput(
            symbol=self._symbol,
            timeframes=timeframes,
            metric=str(self.metric_box.currentText()),
            normalize=bool(self.norm_box.isChecked()),
            tf_candles=tf_candles,
        )

        self.status.setText("Building surface...")
        self.refresh_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = SurfaceWorker(worker_input)
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
            self._thread.wait(300)
            self._thread.deleteLater()
            self._thread = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _cleanup_worker(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
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
        self._stop_worker()
        self._debounce_timer.stop()

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
        if self.isVisible():
            self._schedule_refresh()

    def set_context(self, db: Database, symbol: str) -> None:
        self._db = db
        self._symbol = symbol
        if self.isVisible():
            self._schedule_refresh()
