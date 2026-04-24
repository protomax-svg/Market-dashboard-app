"""
Generic chart panel (PyQtGraph) for one indicator: one or more timeseries.
Includes timeframe selector (5m, 15m, 1h).
"""
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
import pyqtgraph as pg
from pyqtgraph.graphicsItems.DateAxisItem import DateAxisItem

from app.ui.theme import ACCENT, BG_PANEL, BORDER, MUTED, TEXT

TIMEFRAMES = ["5m", "15m", "1h"]
DEFAULT_DISPLAY_DAYS = 90
DISPLAY_DAYS_RANGE = (1, 36500)
PRICE_AXIS_COLOR = "#f7c948"
PRICE_LINE_COLOR = "#ffd166"
HighlightBand = Tuple[Tuple[int, int, int, int], List[Tuple[int, float]]]


def _apply_plot_style(plot: pg.PlotItem) -> None:
    plot.getViewBox().setBackgroundColor(BG_PANEL)
    plot.showGrid(x=True, y=True, alpha=0.18)
    plot.setMenuEnabled(False)
    plot.hideButtons()
    for axis_name in ("left", "bottom", "right"):
        axis = plot.getAxis(axis_name)
        axis_color = PRICE_AXIS_COLOR if axis_name == "right" else TEXT
        pen = pg.mkPen(axis_color, width=1)
        axis.setPen(pen)
        axis.setTextPen(axis_color)


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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame(self)
        self._card.setObjectName("ChartCard")
        root.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(12)
        header.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._title_label = QLabel(display_name, self)
        self._title_label.setObjectName("ChartTitle")
        self._meta_label = QLabel("Waiting for indicator data.", self)
        self._meta_label.setObjectName("ChartMeta")
        title_box.addWidget(self._title_label)
        title_box.addWidget(self._meta_label)
        header.addLayout(title_box, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        tf_label = QLabel("TF", self)
        tf_label.setStyleSheet(f"color: {MUTED};")
        controls.addWidget(tf_label)

        self._tf_combo = QComboBox(self)
        self._tf_combo.addItems(TIMEFRAMES)
        self._tf_combo.setCurrentText("5m")
        self._tf_combo.currentTextChanged.connect(self._on_tf_changed)
        controls.addWidget(self._tf_combo)

        days_label = QLabel("Range", self)
        days_label.setStyleSheet(f"color: {MUTED};")
        controls.addWidget(days_label)

        self._days_spin = QSpinBox(self)
        self._days_spin.setRange(*DISPLAY_DAYS_RANGE)
        self._days_spin.setValue(DEFAULT_DISPLAY_DAYS)
        self._days_spin.setSuffix(" d")
        self._days_spin.valueChanged.connect(self._on_tf_changed)
        controls.addWidget(self._days_spin)

        header.addLayout(controls)
        layout.addLayout(header)

        self._status_label = QLabel("Waiting for indicator data.", self)
        self._status_label.setObjectName("ChartStatus")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        date_axis = DateAxisItem(orientation="bottom")
        self.plot = pg.PlotItem(background=BG_PANEL, axisItems={"bottom": date_axis})
        _apply_plot_style(self.plot)
        self._main_view = self.plot.getViewBox()
        self._main_view.setMouseMode(pg.ViewBox.PanMode)
        self.plot_win = pg.PlotWidget(plotItem=self.plot, parent=self)
        self.plot_win.setBackground(BG_PANEL)
        layout.addWidget(self.plot_win)

        self._curves: Dict[str, pg.PlotDataItem] = {}
        self._price_curve: Optional[pg.PlotCurveItem] = None
        self._price_fill_items: List[Tuple[pg.PlotCurveItem, pg.PlotCurveItem, pg.FillBetweenItem]] = []
        self._colors = [ACCENT, "#34d399", "#7dd3fc", "#f59e0b"]
        self._price_view = pg.ViewBox(enableMouse=False)
        self._price_view.setMouseEnabled(x=False, y=False)
        self.plot.scene().addItem(self._price_view)
        self.plot.getAxis("right").linkToView(self._price_view)
        self._price_view.setXLink(self.plot)
        self._price_view.setZValue(20)
        self._main_view.sigResized.connect(self._sync_price_view)
        self.plot.hideAxis("right")
        self._sync_price_view()
        self._watermark = pg.TextItem(
            text=display_name,
            color=(164, 184, 205, 110),
            anchor=(0.5, 0.5),
        )
        self._watermark.setFont(QFont("Bahnschrift", 14, QFont.Weight.Bold))
        self._watermark.setZValue(100)
        self._watermark.hide()
        self.plot.addItem(self._watermark)

        if compact:
            self.setMaximumHeight(560)
            self.plot_win.setMaximumHeight(430)

    def _on_tf_changed(self, *args: object) -> None:
        self.timeframe_changed.emit(self._tf_combo.currentText())

    def _sync_price_view(self) -> None:
        self._price_view.setGeometry(self._main_view.sceneBoundingRect())
        self._price_view.linkedViewChanged(self._main_view, pg.ViewBox.XAxis)
        x_range, _ = self._main_view.viewRange()
        self._price_view.setXRange(x_range[0], x_range[1], padding=0)

    def _clear_price_overlay(self) -> None:
        if self._price_curve is not None:
            self._price_view.removeItem(self._price_curve)
            self._price_curve = None
        for upper, lower, fill in self._price_fill_items:
            self._price_view.removeItem(fill)
            self._price_view.removeItem(upper)
            self._price_view.removeItem(lower)
        self._price_fill_items.clear()
        self.plot.hideAxis("right")

    def _set_price_overlay(
        self,
        price_series: List[Tuple[int, float]],
        price_label: str,
        highlight_bands: List[HighlightBand],
    ) -> None:
        self._clear_price_overlay()
        if len(price_series) < 2:
            return

        xs = [point[0] / 1000.0 for point in price_series]
        ys = [point[1] for point in price_series]
        y_min = min(ys)
        y_max = max(ys)
        y_span = y_max - y_min
        y_padding = y_span * 0.06 if y_span else max(abs(y_max) * 0.02, 1.0)
        baseline = y_min - y_padding

        self.plot.showAxis("right")
        self.plot.getAxis("right").setLabel(price_label, color=PRICE_AXIS_COLOR)
        self._price_curve = pg.PlotCurveItem(xs, ys, pen=pg.mkPen(PRICE_LINE_COLOR, width=2))
        self._price_curve.setZValue(25)
        self._price_view.addItem(self._price_curve)
        self._sync_price_view()
        self._price_view.setYRange(baseline, y_max + y_padding, padding=0)

        for color, points in highlight_bands:
            if len(points) < 2:
                continue
            band_xs = [point[0] / 1000.0 for point in points]
            band_ys = [point[1] for point in points]
            hidden_pen = pg.mkPen((0, 0, 0, 0))
            upper_curve = pg.PlotCurveItem(band_xs, band_ys, pen=hidden_pen)
            lower_curve = pg.PlotCurveItem(
                band_xs,
                [baseline] * len(points),
                pen=hidden_pen,
            )
            fill = pg.FillBetweenItem(upper_curve, lower_curve, brush=pg.mkBrush(color))
            fill.setZValue(5)
            self._price_view.addItem(upper_curve)
            self._price_view.addItem(lower_curve)
            self._price_view.addItem(fill)
            self._price_fill_items.append((upper_curve, lower_curve, fill))

    def _show_status(self, text: str) -> None:
        self._meta_label.setText(text)
        self._status_label.setText(text)
        self._status_label.show()
        self._watermark.hide()

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

    def set_data(
        self,
        series: Dict[str, List[Tuple[int, float]]],
        price_series: Optional[List[Tuple[int, float]]] = None,
        price_label: str = "Close",
        highlight_bands: Optional[List[HighlightBand]] = None,
    ) -> None:
        clean_series = {key: points for key, points in series.items() if points}
        if not clean_series:
            self.clear("No data in the selected range.")
            return

        price_series = price_series or []
        highlight_bands = highlight_bands or []

        for key, curve in list(self._curves.items()):
            if key not in clean_series:
                self.plot.removeItem(curve)
                del self._curves[key]

        x_min: Optional[float] = None
        x_max: Optional[float] = None
        all_y_values: List[float] = []

        for index, (key, points) in enumerate(clean_series.items()):
            xs = [point[0] / 1000.0 for point in points]
            ys = [point[1] for point in points]
            if not xs:
                continue

            all_y_values.extend(ys)
            series_min = min(xs)
            series_max = max(xs)
            x_min = series_min if x_min is None else min(x_min, series_min)
            x_max = series_max if x_max is None else max(x_max, series_max)

            color = self._colors[index % len(self._colors)]
            if key in self._curves:
                self._curves[key].setData(xs, ys)
            else:
                pen = pg.mkPen(color, width=2)
                self._curves[key] = self.plot.plot(xs, ys, pen=pen, name=key)

        if price_series:
            price_xs = [point[0] / 1000.0 for point in price_series]
            if price_xs:
                price_min = min(price_xs)
                price_max = max(price_xs)
                x_min = price_min if x_min is None else min(x_min, price_min)
                x_max = price_max if x_max is None else max(x_max, price_max)

        if x_min is None or x_max is None or not all_y_values:
            self.clear("No data in the selected range.")
            return

        padding = (x_max - x_min) * 0.02 or 1.0
        self.plot.setXRange(x_min - padding, x_max + padding, padding=0)
        self.plot.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis)

        y_min = min(all_y_values)
        y_max = max(all_y_values)
        x_center = (x_min + x_max) / 2
        y_center = (y_min + y_max) / 2 if y_min != y_max else y_min
        self._watermark.setPos(x_center, y_center)
        self._watermark.show()

        if price_series:
            self._set_price_overlay(price_series, price_label, highlight_bands)
        else:
            self._clear_price_overlay()

        point_count = sum(len(points) for points in clean_series.values()) + len(price_series)
        series_count = len(clean_series) + (1 if price_series else 0)
        meta = f"{series_count} series | {point_count} points | {self.get_display_days()}d window"
        if highlight_bands:
            meta = f"{meta} | {len(highlight_bands)} highlight zones"
        self._meta_label.setText(meta)
        self._status_label.hide()

    def clear(self, status: Optional[str] = None) -> None:
        for curve in list(self._curves.values()):
            self.plot.removeItem(curve)
        self._curves.clear()
        self._clear_price_overlay()
        self._show_status(status or "Waiting for indicator data.")
