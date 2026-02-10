"""
Generic chart panel (PyQtGraph) for one indicator: one or more timeseries.
Includes timeframe selector (5m, 15m, 1h).
"""
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QComboBox, QLabel, QSpinBox
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
import pyqtgraph as pg
from pyqtgraph.graphicsItems.DateAxisItem import DateAxisItem

from app.ui.theme import BG_PANEL, TEXT, ACCENT, BORDER

TIMEFRAMES = ["5m", "15m", "1h"]
DEFAULT_DISPLAY_DAYS = 90
DISPLAY_DAYS_RANGE = (1, 36500)


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
        compact: bool = False,
    ):
        super().__init__(parent)
        self.indicator_id = indicator_id
        self.display_name = display_name
        self._compact = compact
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Toolbar: TF + display days
        toolbar = QHBoxLayout()
        tf_label = QLabel("TF:")
        tf_label.setStyleSheet(f"color: {TEXT};")
        toolbar.addWidget(tf_label)
        self._tf_combo = QComboBox(self)
        self._tf_combo.addItems(TIMEFRAMES)
        self._tf_combo.setCurrentText("5m")
        self._tf_combo.currentTextChanged.connect(self._on_tf_changed)
        toolbar.addWidget(self._tf_combo)
        days_label = QLabel("Days:")
        days_label.setStyleSheet(f"color: {TEXT};")
        toolbar.addWidget(days_label)
        self._days_spin = QSpinBox(self)
        self._days_spin.setRange(*DISPLAY_DAYS_RANGE)
        self._days_spin.setValue(DEFAULT_DISPLAY_DAYS)
        self._days_spin.setSuffix(" d")
        self._days_spin.setStyleSheet(f"color: {TEXT};")
        self._days_spin.valueChanged.connect(self._on_tf_changed)  # trigger refresh on range change
        toolbar.addWidget(self._days_spin)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # X-axis as date/time (Unix timestamp in seconds)
        date_axis = DateAxisItem(orientation="bottom")
        self.plot = pg.PlotItem(background=BG_PANEL, axisItems={"bottom": date_axis})
        _apply_dark_style(self.plot)
        vb = self.plot.getViewBox()
        vb.setMouseMode(pg.ViewBox.PanMode)  # pan only; no rect zoom
        self.plot_win = pg.PlotWidget(plotItem=self.plot, parent=self)
        layout.addWidget(self.plot_win)
        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._colors = [ACCENT, "#34d399", "#6ee7b7", "#a7f3d0"]
        # Watermark: indicator name, center of curve area, bright and large
        self._watermark = pg.TextItem(
            text=display_name,
            color=(220, 220, 220, 200),
            anchor=(0.5, 0.5),
        )
        self._watermark.setFont(QFont("Sans Serif", 14, QFont.Weight.Bold))
        self._watermark.setZValue(100)
        self.plot.addItem(self._watermark)
        if compact:
            self.setMaximumHeight(500)   # total height of bottom-row panel
            self.plot_win.setMaximumHeight(400)  # height of plot area (increase for taller chart)

    def _on_tf_changed(self, *args: object) -> None:
        self.timeframe_changed.emit(self._tf_combo.currentText())

    def get_timeframe(self) -> str:
        return self._tf_combo.currentText()

    def set_timeframe(self, tf: str) -> None:
        if tf in TIMEFRAMES:
            self._tf_combo.setCurrentText(tf)

    def get_display_days(self) -> int:
        return self._days_spin.value()

    def set_display_days(self, days: int) -> None:
        lo, hi = DISPLAY_DAYS_RANGE
        if lo <= days <= hi:
            self._days_spin.setValue(days)

    def set_data(self, series: Dict[str, List[Tuple[int, float]]]) -> None:
        for key, curve in list(self._curves.items()):
            if key not in series:
                self.plot.removeItem(curve)
                del self._curves[key]
        x_min, x_max = None, None
        for i, (key, points) in enumerate(series.items()):
            if not points:
                continue
            xs = [p[0] / 1000.0 for p in points]  # seconds for axis
            ys = [p[1] for p in points]
            if xs:
                if x_min is None:
                    x_min, x_max = min(xs), max(xs)
                else:
                    x_min = min(x_min, min(xs))
                    x_max = max(x_max, max(xs))
            color = self._colors[i % len(self._colors)]
            if key in self._curves:
                self._curves[key].setData(xs, ys)
            else:
                pen = pg.mkPen(color, width=2)
                c = self.plot.plot(xs, ys, pen=pen, name=key)
                self._curves[key] = c
        # Keep chart static: fix X range to data so view doesn't move
        vb = self.plot.getViewBox()
        vb.disableAutoRange(axis=pg.ViewBox.XAxis)
        if x_min is not None and x_max is not None:
            padding = (x_max - x_min) * 0.02 or 1
            self.plot.setXRange(x_min - padding, x_max + padding, padding=0)
            # Position watermark at center of area where curve exists
            all_ys = [p[1] for points in series.values() for p in (points or [])]
            if all_ys:
                y_min_plot = min(all_ys)
                y_max_plot = max(all_ys)
                x_center = (x_min + x_max) / 2
                y_center = (y_min_plot + y_max_plot) / 2
                self._watermark.setPos(x_center, y_center)

    def clear(self) -> None:
        for curve in list(self._curves.values()):
            self.plot.removeItem(curve)
        self._curves.clear()
