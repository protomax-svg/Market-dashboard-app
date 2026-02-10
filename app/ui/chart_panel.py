"""
Generic chart panel (PyQtGraph) for one indicator: one or more timeseries.
Includes timeframe selector (1m, 5m, 15m, 1h).
"""
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QComboBox, QLabel
from PySide6.QtCore import Qt, Signal
import pyqtgraph as pg
from pyqtgraph.graphicsItems.DateAxisItem import DateAxisItem

from app.ui.theme import BG_PANEL, TEXT, ACCENT, BORDER

TIMEFRAMES = ["1m", "5m", "15m", "1h"]


def _apply_dark_style(plot: pg.PlotItem) -> None:
    plot.getViewBox().setBackgroundColor(BG_PANEL)
    plot.showGrid(x=True, y=True, alpha=0.2)
    for ax in ("left", "bottom"):
        pen = pg.mkPen(TEXT, width=1)
        plot.getAxis(ax).setPen(pen)
        plot.getAxis(ax).setTextPen(TEXT)


class ChartPanel(QWidget):
    timeframe_changed = Signal(str)

    def __init__(
        self,
        indicator_id: str,
        display_name: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.indicator_id = indicator_id
        self.display_name = display_name
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Toolbar: TF selector
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

        # X-axis as date/time (Unix timestamp in seconds)
        date_axis = DateAxisItem(orientation="bottom")
        self.plot = pg.PlotItem(background=BG_PANEL, axisItems={"bottom": date_axis})
        _apply_dark_style(self.plot)
        self.plot_win = pg.PlotWidget(plotItem=self.plot, parent=self)
        layout.addWidget(self.plot_win)
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._colors = [ACCENT, "#34d399", "#6ee7b7", "#a7f3d0"]

    def _on_tf_changed(self, tf: str) -> None:
        self.timeframe_changed.emit(tf)

    def get_timeframe(self) -> str:
        return self._tf_combo.currentText()

    def set_timeframe(self, tf: str) -> None:
        if tf in TIMEFRAMES:
            self._tf_combo.setCurrentText(tf)

    def set_data(self, series: Dict[str, List[Tuple[int, float]]]) -> None:
        for key, curve in list(self._curves.items()):
            if key not in series:
                self.plot.removeItem(curve)
                del self._curves[key]
        for i, (key, points) in enumerate(series.items()):
            if not points:
                continue
            xs = [p[0] / 1000.0 for p in points]  # seconds for axis
            ys = [p[1] for p in points]
            color = self._colors[i % len(self._colors)]
            if key in self._curves:
                self._curves[key].setData(xs, ys)
            else:
                pen = pg.mkPen(color, width=2)
                c = self.plot.plot(xs, ys, pen=pen, name=key)
                self._curves[key] = c

    def clear(self) -> None:
        for curve in list(self._curves.values()):
            self.plot.removeItem(curve)
        self._curves.clear()
