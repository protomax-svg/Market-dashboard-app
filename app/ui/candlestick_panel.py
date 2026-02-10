"""
Candlestick chart panel: OHLC with timeframe selector (1m, 5m, 15m, 1h).
Same layout as indicator panels (TF combo, date axis).
"""
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QComboBox, QLabel
from PySide6.QtCore import Signal
import pyqtgraph as pg
from pyqtgraph.graphicsItems.DateAxisItem import DateAxisItem

from app.ui.theme import BG_PANEL, TEXT

TIMEFRAMES = ["1m", "5m", "15m", "1h"]
UP_COLOR = "#22c55e"   # green
DOWN_COLOR = "#ef4444" # red
WICK_COLOR = "#64748b"


def _apply_dark_style(plot: pg.PlotItem) -> None:
    plot.getViewBox().setBackgroundColor(BG_PANEL)
    plot.showGrid(x=True, y=True, alpha=0.2)
    for ax in ("left", "bottom"):
        pen = pg.mkPen(TEXT, width=1)
        plot.getAxis(ax).setPen(pen)
        plot.getAxis(ax).setTextPen(TEXT)


class CandlestickPanel(QWidget):
    timeframe_changed = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        tf_label = QLabel("TF:")
        tf_label.setStyleSheet(f"color: {TEXT};")
        toolbar.addWidget(tf_label)
        self._tf_combo = QComboBox(self)
        self._tf_combo.addItems(TIMEFRAMES)
        self._tf_combo.setCurrentText("1m")
        self._tf_combo.currentTextChanged.connect(self._on_tf_changed)
        toolbar.addWidget(self._tf_combo)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        date_axis = DateAxisItem(orientation="bottom")
        self.plot = pg.PlotItem(background=BG_PANEL, axisItems={"bottom": date_axis})
        _apply_dark_style(self.plot)
        self.plot_win = pg.PlotWidget(plotItem=self.plot, parent=self)
        layout.addWidget(self.plot_win)

        self._wick_item: Optional[pg.PlotDataItem] = None
        self._body_item: Optional[pg.BarGraphItem] = None

    def _on_tf_changed(self, tf: str) -> None:
        self.timeframe_changed.emit(tf)

    def get_timeframe(self) -> str:
        return self._tf_combo.currentText()

    def set_timeframe(self, tf: str) -> None:
        if tf in TIMEFRAMES:
            self._tf_combo.setCurrentText(tf)

    def set_data(self, candles: List[Dict[str, Any]]) -> None:
        """Set OHLC data exactly as in DB. Each candle: open_time (ms), open, high, low, close (numeric)."""
        if not candles:
            self.clear()
            return

        n = len(candles)
        xs_sec = [int(c["open_time"]) / 1000.0 for c in candles]
        opens = [float(c["open"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]

        # Wicks: one segment per candle (t, low)-(t, high); NaN breaks connection between candles
        wick_xs: List[float] = []
        wick_ys: List[float] = []
        for i in range(n):
            t = xs_sec[i]
            wick_xs.extend([t, t, float("nan")])
            wick_ys.extend([lows[i], highs[i], float("nan")])

        # Bodies: exactly open/close from DB — height = |close - open|, bottom = min(open, close).
        # BarGraphItem uses y0 = bottom edge (y = center would place bodies wrong).
        heights = [abs(c - o) for o, c in zip(opens, closes)]
        bottoms = [min(o, c) for o, c in zip(opens, closes)]
        if n >= 2:
            width = 0.6 * (xs_sec[-1] - xs_sec[0]) / max(1, n - 1)
        else:
            width = 60.0
        brushes = [UP_COLOR if c >= o else DOWN_COLOR for o, c in zip(opens, closes)]

        if self._wick_item is not None:
            self.plot.removeItem(self._wick_item)
        self._wick_item = pg.PlotDataItem(
            wick_xs, wick_ys,
            pen=pg.mkPen(WICK_COLOR, width=1),
            connect="finite",
        )
        self._wick_item.setZValue(0)
        self.plot.addItem(self._wick_item)

        if self._body_item is not None:
            self.plot.removeItem(self._body_item)
        n_bars = len(xs_sec)
        self._body_item = pg.BarGraphItem(
            x=xs_sec,
            height=heights,
            width=width,
            y0=bottoms,
            brushes=brushes,
            pens=[pg.mkPen(None)] * n_bars,
        )
        self._body_item.setZValue(1)  # draw bodies on top of wicks
        self.plot.addItem(self._body_item)

    def clear(self) -> None:
        if self._wick_item is not None:
            self.plot.removeItem(self._wick_item)
            self._wick_item = None
        if self._body_item is not None:
            self.plot.removeItem(self._body_item)
            self._body_item = None
