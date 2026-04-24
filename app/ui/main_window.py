"""
Main window: dashboard layout, menus, persistence, and background ingestion services.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.config import ensure_storage_dir, get_custom_indicators_dir, get_db_path, load_config, save_config
from app.indicators import discover_indicators
from app.indicators.base import IndicatorBase, IndicatorSeriesInput
from app.ingestion.candle_service import CandleIngestionService
from app.ingestion.liquidation_client import LiquidationClient
from app.storage.db import Database
from app.ui.chart_panel import ChartPanel
from app.ui.date_range_dialog import DateRangeDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import STYLESHEET

try:
    from app.ui.surface3d_window import Surface3DWindow
except Exception:
    Surface3DWindow = None  # type: ignore

logger = logging.getLogger(__name__)

SETTINGS_ORG = "MarketMetrics"
SETTINGS_APP = "MarketMetrics"
INDICATOR_PANELS_KEY = "layout/indicator_panels"
REGIME_PANEL_KEY = "layout/regime_panel"
BALANCED_REGIME_PANEL_KEY = "layout/balanced_regime_panel"
MAIN_SPLITTER_KEY = "layout/main_splitter_sizes"
LOWER_SPLITTER_KEY = "layout/lower_splitter_sizes"
REGIME_INDICATOR_ID = "regime_index"
BALANCED_REGIME_INDICATOR_ID = "balanced_regime_index"
MAX_LIQUIDATIONS_FOR_REFRESH = 4000
REGIME_HIGHLIGHT_HIGH_COLOR = (239, 68, 68, 70)
REGIME_HIGHLIGHT_LOW_COLOR = (34, 197, 94, 60)
REGIME_OVERLAY_CONFIG: Dict[str, Tuple[str, str, str]] = {
    REGIME_INDICATOR_ID: ("regime", "regime_highlight_low", "regime_highlight_high"),
    BALANCED_REGIME_INDICATOR_ID: (
        "balanced_regime",
        "balanced_regime_highlight_low",
        "balanced_regime_highlight_high",
    ),
}

PricePoint = Tuple[int, float]
HighlightBand = Tuple[Tuple[int, int, int, int], List[PricePoint]]


def _interpolate_threshold_cross_time(
    start_t: int,
    start_v: float,
    end_t: int,
    end_v: float,
    threshold: float,
) -> int:
    if end_t <= start_t or end_v == start_v:
        return end_t
    fraction = (threshold - start_v) / (end_v - start_v)
    fraction = max(0.0, min(1.0, fraction))
    return int(start_t + (end_t - start_t) * fraction)


def _interpolate_point_value(points: List[PricePoint], target_t: int) -> Optional[float]:
    if not points:
        return None
    if target_t <= points[0][0]:
        return float(points[0][1])
    for index in range(1, len(points)):
        prev_t, prev_v = points[index - 1]
        curr_t, curr_v = points[index]
        if target_t <= curr_t:
            if curr_t == prev_t:
                return float(curr_v)
            ratio = (target_t - prev_t) / (curr_t - prev_t)
            return float(prev_v + (curr_v - prev_v) * ratio)
    return float(points[-1][1])


def _extract_segment(points: List[PricePoint], start_t: int, end_t: int) -> List[PricePoint]:
    if len(points) < 2 or end_t <= start_t:
        return []
    start_v = _interpolate_point_value(points, start_t)
    end_v = _interpolate_point_value(points, end_t)
    if start_v is None or end_v is None:
        return []

    segment: List[PricePoint] = [(start_t, start_v)]
    for point_t, point_v in points:
        if start_t < point_t < end_t:
            segment.append((point_t, float(point_v)))
    segment.append((end_t, end_v))

    deduped: List[PricePoint] = []
    for point_t, point_v in segment:
        if deduped and deduped[-1][0] == point_t:
            deduped[-1] = (point_t, point_v)
        else:
            deduped.append((point_t, point_v))
    return deduped if len(deduped) >= 2 else []


def _threshold_intervals(
    regime_points: List[PricePoint],
    threshold: float,
    *,
    above: bool,
) -> List[Tuple[int, int]]:
    if len(regime_points) < 2:
        return []

    intervals: List[Tuple[int, int]] = []
    prev_t, prev_v = regime_points[0]
    prev_active = prev_v > threshold if above else prev_v < threshold
    start_t = prev_t if prev_active else None

    for curr_t, curr_v in regime_points[1:]:
        curr_active = curr_v > threshold if above else curr_v < threshold
        if not prev_active and curr_active:
            start_t = _interpolate_threshold_cross_time(prev_t, prev_v, curr_t, curr_v, threshold)
        elif prev_active and not curr_active:
            end_t = _interpolate_threshold_cross_time(prev_t, prev_v, curr_t, curr_v, threshold)
            if start_t is not None and end_t > start_t:
                intervals.append((start_t, end_t))
            start_t = None
        prev_t, prev_v, prev_active = curr_t, curr_v, curr_active

    if prev_active and start_t is not None and prev_t > start_t:
        intervals.append((start_t, prev_t))
    return intervals


def _build_regime_price_overlay(
    candles: List[Dict[str, Any]],
    regime_points: List[PricePoint],
    low_threshold: float,
    high_threshold: float,
) -> Tuple[List[PricePoint], List[HighlightBand]]:
    price_points = [
        (int(candle["open_time"]), float(candle["close"]))
        for candle in candles
        if candle.get("open_time") is not None and candle.get("close") is not None
    ]
    if len(price_points) < 2:
        return ([], [])

    if len(regime_points) >= 2:
        trimmed_price = _extract_segment(price_points, regime_points[0][0], regime_points[-1][0])
        if trimmed_price:
            price_points = trimmed_price

    if low_threshold >= high_threshold or len(regime_points) < 2:
        return (price_points, [])

    highlight_bands: List[HighlightBand] = []
    for start_t, end_t in _threshold_intervals(regime_points, high_threshold, above=True):
        segment = _extract_segment(price_points, start_t, end_t)
        if len(segment) >= 2:
            highlight_bands.append((REGIME_HIGHLIGHT_HIGH_COLOR, segment))

    for start_t, end_t in _threshold_intervals(regime_points, low_threshold, above=False):
        segment = _extract_segment(price_points, start_t, end_t)
        if len(segment) >= 2:
            highlight_bands.append((REGIME_HIGHLIGHT_LOW_COLOR, segment))

    highlight_bands.sort(key=lambda item: item[1][0][0])
    return (price_points, highlight_bands)


def _make_indicator_placeholder_card(title: str, message: str, parent: QWidget) -> QFrame:
    placeholder_card = QFrame(parent)
    placeholder_card.setObjectName("ChartCard")
    placeholder_layout = QVBoxLayout(placeholder_card)
    placeholder_layout.setContentsMargins(12, 12, 12, 12)
    placeholder_layout.setSpacing(6)

    placeholder_title = QLabel(title, placeholder_card)
    placeholder_title.setObjectName("ChartTitle")
    placeholder_layout.addWidget(placeholder_title)

    placeholder = QLabel(message, placeholder_card)
    placeholder.setObjectName("ChartStatus")
    placeholder.setWordWrap(True)
    placeholder_layout.addWidget(placeholder)
    return placeholder_card


class MainWindow(QMainWindow):
    candle_progress = Signal(str)
    retention_done = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MarketMetrics")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(900, 600)
        self.resize(1200, 700)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("Preparing workspace...")
        self.candle_progress.connect(self._on_candle_progress)

        self._config = load_config()
        ensure_storage_dir(os.path.dirname(get_db_path(self._config)))
        self._db = Database(get_db_path(self._config))
        self._candle_service: Optional[CandleIngestionService] = None
        self._liquidation_client: Optional[LiquidationClient] = None

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._project_indicators_dir = os.path.join(project_root, "indicators")
        self._composite_indicators_dir = os.path.join(self._project_indicators_dir, "composite")
        self._custom_indicators_dir = get_custom_indicators_dir(self._config)

        classes, discover_errors = discover_indicators(
            self._project_indicators_dir,
            self._custom_indicators_dir,
            self._composite_indicators_dir,
            reload_plugins=False,
        )
        for err in discover_errors:
            logger.warning("Indicator discover: %s", err)

        self._indicator_classes: List[Type[IndicatorBase]] = classes
        self._indicator_class_by_id: Dict[str, Type[IndicatorBase]] = {
            indicator.id: indicator for indicator in self._indicator_classes
        }
        self._date_range_days = int(self._config.get("date_range_days", 90))
        self._surface3d_window: Optional[Any] = None
        self._regime_panel: Optional[ChartPanel] = None
        self._balanced_regime_panel: Optional[ChartPanel] = None
        self._main_splitter: Optional[QSplitter] = None
        self._lower_splitter: Optional[QSplitter] = None
        self._indicator_panels: Dict[str, ChartPanel] = {}
        self._layout_restored = False
        self._startup_in_progress = True
        self._refresh_pending = False
        self._last_regime_index_update_ms = 0
        self._last_balanced_regime_update_ms = 0
        self.REGIME_INDEX_REFRESH_INTERVAL_MS = 15 * 60 * 1000

        self._hero_subtitle: Optional[QLabel] = None
        self._summary_symbol: Optional[QLabel] = None
        self._summary_range: Optional[QLabel] = None
        self._summary_panels: Optional[QLabel] = None
        self._summary_storage: Optional[QLabel] = None

        self._build_central_tabs()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._schedule_refresh_all_indicators)
        self._refresh_timer.start(60 * 1000)

        QTimer.singleShot(0, self._deferred_startup)

    def _deferred_startup(self) -> None:
        self._build_menus()
        self._restore_layout_only_tf_and_tab()
        self._start_services()

        self.retention_done.connect(self._on_retention_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(target=self._run_retention_in_thread, daemon=True)
        thread.start()

        self._startup_in_progress = False
        self.statusBar().showMessage("Starting services and restoring charts...")

    def _run_retention_in_thread(self) -> None:
        try:
            self._apply_retention()
        except Exception as exc:
            logger.exception("Retention failed: %s", exc)
        self.retention_done.emit()

    def _on_retention_done(self) -> None:
        try:
            self.retention_done.disconnect(self._on_retention_done)
        except Exception:
            pass
        self._reset_regime_refresh_timers()
        self.statusBar().showMessage("Ready", 4000)
        QTimer.singleShot(500, self._schedule_refresh_all_indicators)

    def _make_summary_pill(self) -> QLabel:
        pill = QLabel(self)
        pill.setObjectName("HeroPill")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setMinimumWidth(110)
        return pill

    def _update_header_summary(self) -> None:
        if not all(
            [
                self._hero_subtitle,
                self._summary_symbol,
                self._summary_range,
                self._summary_panels,
                self._summary_storage,
            ]
        ):
            return

        symbol = str(self._config.get("symbol", "BTCUSDT")).upper()
        storage_path = Path(self._config.get("storage_path") or os.path.dirname(get_db_path(self._config)))
        storage_name = storage_path.name or str(storage_path)
        total_panels = len([cls for cls in self._indicator_classes if cls.id != REGIME_INDICATOR_ID])
        if self._regime_panel is not None:
            total_panels += 1

        self._hero_subtitle.setText(
            "Live candles, liquidation pressure, and multi-timeframe indicator scans for the selected market."
        )
        self._summary_symbol.setText(f"Symbol  {symbol}")
        self._summary_range.setText(f"History  {self._date_range_days}d")
        self._summary_panels.setText(f"Panels  {total_panels}")
        self._summary_storage.setText(f"Storage  {storage_name}")

    def _show_balanced_regime_panel(self) -> bool:
        return bool(self._config.get("show_balanced_regime_panel", True))

    def _reset_regime_refresh_timers(self) -> None:
        self._last_regime_index_update_ms = 0
        self._last_balanced_regime_update_ms = 0

    def _rebuild_dashboard_layout(self) -> None:
        self._regime_panel = None
        self._balanced_regime_panel = None
        self._main_splitter = None
        self._lower_splitter = None
        self._indicator_panels.clear()

        old_central = self.takeCentralWidget()
        if old_central is not None:
            old_central.deleteLater()

        self._build_central_tabs()

    def _default_main_splitter_sizes(self) -> List[int]:
        if self._balanced_regime_panel is not None:
            return [460, 320]
        return [520, 280]

    def _default_lower_splitter_sizes(self) -> List[int]:
        panel_count = max(1, len(self._indicator_panels))
        return [360] * panel_count

    def _read_splitter_sizes(self, key: str) -> Optional[List[int]]:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        raw_value = settings.value(key)
        if raw_value is None:
            return None
        try:
            data = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            if isinstance(data, list):
                sizes = [int(value) for value in data if int(value) > 0]
                return sizes or None
        except Exception:
            return None
        return None

    def _apply_splitter_sizes(self) -> None:
        if self._main_splitter is not None:
            main_sizes = self._read_splitter_sizes(MAIN_SPLITTER_KEY) or self._default_main_splitter_sizes()
            if len(main_sizes) == self._main_splitter.count():
                self._main_splitter.setSizes(main_sizes)
        if self._lower_splitter is not None:
            lower_sizes = self._read_splitter_sizes(LOWER_SPLITTER_KEY) or self._default_lower_splitter_sizes()
            if len(lower_sizes) == self._lower_splitter.count():
                self._lower_splitter.setSizes(lower_sizes)

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        self._indicators_menu = QMenu("Indicators", self)
        menubar.addMenu(self._indicators_menu)
        self._rebuild_indicators_menu()

        date_range_menu = menubar.addMenu("Date Range")
        date_range_action = QAction("Set date range...", self)
        date_range_action.triggered.connect(self._open_date_range)
        date_range_menu.addAction(date_range_action)

        settings_menu = menubar.addMenu("Settings")
        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(settings_action)

        help_menu = menubar.addMenu("Help")
        help_action = QAction("About", self)
        help_action.triggered.connect(self._show_about)
        help_menu.addAction(help_action)

    def _build_central_tabs(self) -> None:
        central = QWidget(self)
        central.setObjectName("CentralCanvas")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        show_balanced_panel = self._show_balanced_regime_panel()

        self._main_splitter = QSplitter(Qt.Orientation.Vertical, central)
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setHandleWidth(10)
        layout.addWidget(self._main_splitter)

        regime_cls = self._indicator_class_by_id.get(REGIME_INDICATOR_ID)
        if regime_cls is not None:
            self._regime_panel = ChartPanel(
                REGIME_INDICATOR_ID,
                regime_cls.display_name,
                self,
                compact=False,
            )
            self._regime_panel.timeframe_changed.connect(self._schedule_regime_refresh)
            self._regime_panel.setMinimumHeight(240)
            self._main_splitter.addWidget(self._regime_panel)
        else:
            self._regime_panel = None
            self._main_splitter.addWidget(
                _make_indicator_placeholder_card(
                    "Regime Index unavailable",
                    "The regime_index indicator was not found. Use Indicators > Reload Indicators after fixing the plugin.",
                    self,
                ),
            )

        if show_balanced_panel:
            balanced_cls = self._indicator_class_by_id.get(BALANCED_REGIME_INDICATOR_ID)
            if balanced_cls is not None:
                self._balanced_regime_panel = ChartPanel(
                    BALANCED_REGIME_INDICATOR_ID,
                    balanced_cls.display_name,
                    self,
                    compact=False,
                )
                self._balanced_regime_panel.timeframe_changed.connect(self._schedule_regime_refresh)
                self._balanced_regime_panel.setMinimumHeight(220)
                self._main_splitter.addWidget(self._balanced_regime_panel)
            else:
                self._balanced_regime_panel = None
                self._main_splitter.addWidget(
                    _make_indicator_placeholder_card(
                        "Balanced Regime Index unavailable",
                        "The balanced_regime_index indicator was not found. Use Indicators > Reload Indicators after fixing the plugin.",
                        self,
                    ),
                )
        else:
            self._balanced_regime_panel = None
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setMinimumHeight(220)

            self._lower_splitter = QSplitter(Qt.Orientation.Horizontal, scroll)
            self._lower_splitter.setChildrenCollapsible(False)
            self._lower_splitter.setHandleWidth(10)

            for indicator_cls in self._indicator_classes:
                if indicator_cls.id == REGIME_INDICATOR_ID:
                    continue
                if indicator_cls.id in self._indicator_panels:
                    continue

                panel = ChartPanel(indicator_cls.id, indicator_cls.display_name, self, compact=True)
                panel.setMinimumWidth(240)
                if indicator_cls.id == BALANCED_REGIME_INDICATOR_ID:
                    panel.timeframe_changed.connect(self._schedule_regime_refresh)
                else:
                    panel.timeframe_changed.connect(self._schedule_refresh_all_indicators)
                self._indicator_panels[indicator_cls.id] = panel
                self._lower_splitter.addWidget(panel)

            if not self._indicator_panels:
                scroll.setWidget(
                    _make_indicator_placeholder_card(
                        "Indicators unavailable",
                        "No secondary indicators are available yet.",
                        self,
                    )
                )
                self._lower_splitter = None
            else:
                scroll.setWidget(self._lower_splitter)
            self._main_splitter.addWidget(scroll)

        if self._main_splitter is not None and self._main_splitter.count() >= 2:
            self._main_splitter.setStretchFactor(0, 3)
            self._main_splitter.setStretchFactor(1, 2)
        if self._lower_splitter is not None:
            for index in range(self._lower_splitter.count()):
                self._lower_splitter.setStretchFactor(index, 1)

        self.setCentralWidget(central)
        self._apply_splitter_sizes()
        QTimer.singleShot(0, self._apply_splitter_sizes)
        self._update_header_summary()

    def _restore_layout_only_tf_and_tab(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        regime_json = settings.value(REGIME_PANEL_KEY)
        if regime_json and self._regime_panel is not None:
            try:
                data = json.loads(regime_json) if isinstance(regime_json, str) else regime_json
                if isinstance(data, dict):
                    self._regime_panel.set_timeframe(data.get("tf", "5m"))
                    if "days" in data:
                        self._regime_panel.set_display_days(int(data["days"]))
            except Exception:
                pass

        panels_json = settings.value(INDICATOR_PANELS_KEY)
        panel_layouts: Dict[str, Any] = {}
        if panels_json:
            try:
                data = json.loads(panels_json) if isinstance(panels_json, str) else panels_json
                panel_layouts = data if isinstance(data, dict) else {}
                for indicator_id, cfg in panel_layouts.items():
                    if indicator_id == BALANCED_REGIME_INDICATOR_ID and self._balanced_regime_panel is not None:
                        continue
                    panel = self._indicator_panels.get(indicator_id)
                    if panel is not None and isinstance(cfg, dict):
                        panel.set_timeframe(cfg.get("tf", "5m"))
                        if "days" in cfg:
                            panel.set_display_days(int(cfg["days"]))
            except Exception:
                pass

        if self._balanced_regime_panel is None:
            return

        balanced_json = settings.value(BALANCED_REGIME_PANEL_KEY)
        balanced_cfg: Optional[Dict[str, Any]] = None
        if balanced_json:
            try:
                candidate = json.loads(balanced_json) if isinstance(balanced_json, str) else balanced_json
                if isinstance(candidate, dict):
                    balanced_cfg = candidate
            except Exception:
                balanced_cfg = None
        if balanced_cfg is None:
            candidate = panel_layouts.get(BALANCED_REGIME_INDICATOR_ID)
            if isinstance(candidate, dict):
                balanced_cfg = candidate
        if isinstance(balanced_cfg, dict):
            self._balanced_regime_panel.set_timeframe(balanced_cfg.get("tf", "5m"))
            if "days" in balanced_cfg:
                self._balanced_regime_panel.set_display_days(int(balanced_cfg["days"]))
        elif self._regime_panel is not None:
            self._balanced_regime_panel.set_timeframe(self._regime_panel.get_timeframe())
            self._balanced_regime_panel.set_display_days(self._regime_panel.get_display_days())

    def _rebuild_indicators_menu(self) -> None:
        self._indicators_menu.clear()

        if Surface3DWindow is not None:
            action = QAction("Vol Stability (3D)...", self)
            action.triggered.connect(self._open_vol_stability_window)
            self._indicators_menu.addAction(action)

        self._indicators_menu.addSeparator()

        reload_action = QAction("Reload Indicators", self)
        reload_action.triggered.connect(self._reload_indicators)
        self._indicators_menu.addAction(reload_action)

        open_folder_action = QAction("Open Indicators Folder", self)
        open_folder_action.triggered.connect(self._open_indicators_folder)
        self._indicators_menu.addAction(open_folder_action)

    def _reload_indicators(self) -> None:
        self._save_layout()
        classes, errors = discover_indicators(
            self._project_indicators_dir,
            self._custom_indicators_dir,
            self._composite_indicators_dir,
            reload_plugins=True,
        )
        for err in errors:
            logger.warning("Indicator reload: %s", err)

        if errors:
            self.statusBar().showMessage(f"Indicator reload: {len(errors)} failed (see log)", 8000)
        else:
            self.statusBar().showMessage("Indicators reloaded", 3000)

        self._indicator_classes = classes
        self._indicator_class_by_id = {indicator.id: indicator for indicator in self._indicator_classes}

        self._rebuild_dashboard_layout()
        self._restore_layout_only_tf_and_tab()
        self._rebuild_indicators_menu()
        self._reset_regime_refresh_timers()
        self._schedule_refresh_all_indicators()

    def _open_indicators_folder(self) -> None:
        path = self._custom_indicators_dir
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        url = QUrl.fromLocalFile(path)
        if not QDesktopServices.openUrl(url):
            self.statusBar().showMessage(f"Could not open: {path}", 5000)

    def _open_vol_stability_window(self) -> None:
        if Surface3DWindow is None:
            return

        if self._surface3d_window is not None and self._surface3d_window.isVisible():
            self._surface3d_window.raise_()
            self._surface3d_window.activateWindow()
            return

        if self._surface3d_window is not None:
            self._surface3d_window.deleteLater()
            self._surface3d_window = None

        symbol = str(self._config.get("symbol", "BTCUSDT")).upper()
        lookback_hours = self._date_range_days * 24
        window = Surface3DWindow(
            self._db,
            symbol=symbol,
            lookback_hours=lookback_hours,
            parent=None,
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.destroyed.connect(lambda: setattr(self, "_surface3d_window", None))
        self._surface3d_window = window
        window.show()

    def _restore_layout(self) -> None:
        self._restore_layout_only_tf_and_tab()

    def _save_layout(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)

        if self._regime_panel is not None:
            regime_data = {
                "tf": self._regime_panel.get_timeframe(),
                "days": self._regime_panel.get_display_days(),
            }
            settings.setValue(REGIME_PANEL_KEY, json.dumps(regime_data))

        if self._balanced_regime_panel is not None:
            balanced_data = {
                "tf": self._balanced_regime_panel.get_timeframe(),
                "days": self._balanced_regime_panel.get_display_days(),
            }
            settings.setValue(BALANCED_REGIME_PANEL_KEY, json.dumps(balanced_data))

        panels_data: Dict[str, Dict[str, Any]] = {}
        if self._balanced_regime_panel is not None:
            panels_data[BALANCED_REGIME_INDICATOR_ID] = {
                "tf": self._balanced_regime_panel.get_timeframe(),
                "days": self._balanced_regime_panel.get_display_days(),
            }
        for indicator_id, panel in self._indicator_panels.items():
            panels_data[indicator_id] = {
                "tf": panel.get_timeframe(),
                "days": panel.get_display_days(),
            }
        settings.setValue(INDICATOR_PANELS_KEY, json.dumps(panels_data))
        if self._main_splitter is not None:
            settings.setValue(MAIN_SPLITTER_KEY, json.dumps(self._main_splitter.sizes()))
        if self._lower_splitter is not None:
            settings.setValue(LOWER_SPLITTER_KEY, json.dumps(self._lower_splitter.sizes()))
        settings.setValue("layout/geometry", self.saveGeometry())

    def _auto_history_start_date(self, days: Optional[int] = None) -> str:
        lookback_days = max(1, int(days if days is not None else self._date_range_days))
        start_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        return start_dt.strftime("%Y-%m-%d")

    def _effective_candle_start_date(self, days: Optional[int] = None) -> str:
        configured_start = (self._config.get("candle_start_date") or "").strip()
        auto_start = self._auto_history_start_date(days)
        if not configured_start:
            return auto_start
        return min(configured_start, auto_start)

    def _minimum_required_history_days(self) -> int:
        required_days = max(1, int(self._date_range_days))
        configured_start = (self._config.get("candle_start_date") or "").strip()
        if not configured_start:
            return required_days
        try:
            start_dt = datetime.strptime(configured_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return required_days
        keep_days_from_start = max(1, (datetime.now(timezone.utc).date() - start_dt.date()).days + 1)
        return max(required_days, keep_days_from_start)

    def _sync_history_window_with_display_range(self) -> bool:
        if self._config.get("retention_mode", "days") != "days":
            return False
        keep_days = int(self._config.get("retention_days", 90))
        required_days = self._minimum_required_history_days()
        if keep_days >= required_days:
            return False
        self._config["retention_days"] = required_days
        save_config(self._config)
        return True

    def _open_date_range(self) -> None:
        previous_effective_start = self._effective_candle_start_date(self._date_range_days)
        dlg = DateRangeDialog(self._date_range_days, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_range_days = dlg.get_days()
            self._config["date_range_days"] = self._date_range_days
            retention_changed = self._sync_history_window_with_display_range()
            save_config(self._config)

            new_effective_start = self._effective_candle_start_date(self._date_range_days)
            should_restart_services = retention_changed or (new_effective_start != previous_effective_start)

            if should_restart_services:
                self._stop_services()
                self._start_services()

            if self._surface3d_window is not None and self._surface3d_window.isVisible():
                self._surface3d_window.set_lookback_hours(self._date_range_days * 24)

            self._reset_regime_refresh_timers()
            self._update_header_summary()
            self._schedule_refresh_all_indicators()
            if should_restart_services:
                self.statusBar().showMessage(
                    f"Extending history window and backfilling candles from {new_effective_start}.",
                    7000,
                )
            else:
                self.statusBar().showMessage("Display range updated.", 4000)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        old_config = dict(self._config)
        self._config = dlg.get_config()
        save_config(self._config)

        old_db_path = os.path.normcase(os.path.abspath(get_db_path(old_config)))
        new_db_path = os.path.normcase(os.path.abspath(get_db_path(self._config)))
        storage_changed = old_db_path != new_db_path

        old_custom_dir = os.path.normcase(os.path.abspath(self._custom_indicators_dir))
        self._custom_indicators_dir = get_custom_indicators_dir(self._config)
        custom_dir_changed = old_custom_dir != os.path.normcase(os.path.abspath(self._custom_indicators_dir))

        old_symbol = str(old_config.get("symbol", "BTCUSDT")).upper()
        new_symbol = str(self._config.get("symbol", "BTCUSDT")).upper()
        symbol_changed = old_symbol != new_symbol
        layout_changed = self._show_balanced_regime_panel() != bool(old_config.get("show_balanced_regime_panel", True))
        if custom_dir_changed or layout_changed:
            self._save_layout()

        self._stop_services()

        if storage_changed:
            ensure_storage_dir(os.path.dirname(get_db_path(self._config)))
            self._db = Database(get_db_path(self._config))

        self._apply_retention()
        self._start_services()

        if self._surface3d_window is not None:
            self._surface3d_window.set_context(self._db, new_symbol)
            self._surface3d_window.set_lookback_hours(self._date_range_days * 24)

        if custom_dir_changed:
            self._reload_indicators()
        elif layout_changed:
            self._rebuild_dashboard_layout()
            self._restore_layout_only_tf_and_tab()

        self._reset_regime_refresh_timers()
        self._update_header_summary()
        self._schedule_refresh_all_indicators()

        fragments = ["services restarted"]
        if storage_changed:
            fragments.append("database switched")
        if symbol_changed:
            fragments.append(f"symbol set to {new_symbol}")
        if layout_changed:
            fragments.append("dashboard layout updated")
        self.statusBar().showMessage(f"Settings saved: {', '.join(fragments)}", 6000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About MarketMetrics",
            "MarketMetrics is a desktop dashboard for candles, liquidations, and custom indicators.",
        )

    def _apply_retention(self) -> None:
        mode = self._config.get("retention_mode", "days")
        if mode == "days":
            keep = max(int(self._config.get("retention_days", 90)), self._minimum_required_history_days())
            if keep != int(self._config.get("retention_days", 90)):
                self._config["retention_days"] = keep
                save_config(self._config)
            self._db.prune_by_days(keep)
        else:
            max_gb = float(self._config.get("retention_size_gb", 5.0))
            self._db.prune_by_size_gb(max_gb)

    def _on_candle_progress(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _start_services(self) -> None:
        symbol = str(self._config.get("symbol", "BTCUSDT")).upper()
        poll = float(self._config.get("candle_poll_interval_sec", 60))
        start_date = self._effective_candle_start_date()

        self._candle_service = CandleIngestionService(
            self._db,
            symbol,
            poll_interval_sec=poll,
            on_progress=lambda message: self.candle_progress.emit(message),
            start_date=start_date or None,
        )
        self._candle_service.start()

        ngrok = (self._config.get("ngrok_liquidations_url") or "").strip()
        if ngrok:
            reconnect = float(self._config.get("liquidations_reconnect_delay_sec", 5))
            self._liquidation_client = LiquidationClient(
                self._db,
                ngrok,
                symbol=symbol,
                reconnect_delay_sec=reconnect,
            )
            self._liquidation_client.start()

    def _stop_services(self) -> None:
        if self._candle_service:
            self._candle_service.stop()
            self._candle_service = None
        if self._liquidation_client:
            self._liquidation_client.stop()
            self._liquidation_client = None

    def _schedule_regime_refresh(self, *_args: object) -> None:
        self._reset_regime_refresh_timers()
        self._schedule_refresh_all_indicators()

    def _schedule_refresh_all_indicators(self) -> None:
        if self._startup_in_progress or self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self._refresh_all_indicators_safe)

    def _refresh_all_indicators_safe(self) -> None:
        self._refresh_pending = False
        self._refresh_all_indicators()

    def _refresh_all_indicators(self) -> None:
        if self._startup_in_progress:
            return

        symbol = str(self._config.get("symbol", "BTCUSDT")).upper()
        end_ms = int(time.time() * 1000)

        if self._regime_panel is not None:
            if end_ms - self._last_regime_index_update_ms >= self.REGIME_INDEX_REFRESH_INTERVAL_MS:
                regime_days = self._regime_panel.get_display_days()
                regime_start_ms = end_ms - regime_days * 24 * 60 * 60 * 1000
                updated = self._refresh_one_indicator(
                    REGIME_INDICATOR_ID,
                    self._regime_panel,
                    regime_start_ms,
                    end_ms,
                    symbol,
                )
                if updated:
                    self._last_regime_index_update_ms = end_ms

        if self._balanced_regime_panel is not None:
            if end_ms - self._last_balanced_regime_update_ms >= self.REGIME_INDEX_REFRESH_INTERVAL_MS:
                balanced_days = self._balanced_regime_panel.get_display_days()
                balanced_start_ms = end_ms - balanced_days * 24 * 60 * 60 * 1000
                updated = self._refresh_one_indicator(
                    BALANCED_REGIME_INDICATOR_ID,
                    self._balanced_regime_panel,
                    balanced_start_ms,
                    end_ms,
                    symbol,
                )
                if updated:
                    self._last_balanced_regime_update_ms = end_ms

        for indicator_id, panel in self._indicator_panels.items():
            if (
                indicator_id == BALANCED_REGIME_INDICATOR_ID
                and end_ms - self._last_balanced_regime_update_ms < self.REGIME_INDEX_REFRESH_INTERVAL_MS
            ):
                continue
            days = panel.get_display_days()
            start_ms = end_ms - days * 24 * 60 * 60 * 1000
            updated = self._refresh_one_indicator(indicator_id, panel, start_ms, end_ms, symbol)
            if updated and indicator_id == BALANCED_REGIME_INDICATOR_ID:
                self._last_balanced_regime_update_ms = end_ms

    def _refresh_one_indicator(
        self,
        indicator_id: str,
        panel: ChartPanel,
        start_ms: int,
        end_ms: int,
        symbol: str,
    ) -> bool:
        cls = self._indicator_class_by_id.get(indicator_id)
        if cls is None:
            panel.clear("Indicator is unavailable.")
            return False

        timeframe = panel.get_timeframe()
        required_inputs = getattr(cls, "required_inputs", []) or []
        required_ids = getattr(cls, "required_indicator_ids", None) or []
        input_names = {item.get("name") for item in required_inputs}

        needs_liquidations = "liquidations" in input_names
        needs_candles = bool(required_ids) or "candles" in input_names or not input_names

        liquidations = self._db.get_liquidations_1m(symbol, start_ms, end_ms) if needs_liquidations else []
        if len(liquidations) > MAX_LIQUIDATIONS_FOR_REFRESH:
            liquidations = liquidations[-MAX_LIQUIDATIONS_FOR_REFRESH:]

        candles = self._db.get_candles(symbol, timeframe, start_ms, end_ms) if needs_candles else []

        if needs_candles and not candles:
            panel.clear("No candle data in the selected range.")
            return False
        if needs_liquidations and not liquidations:
            panel.clear("Waiting for liquidation data.")
            return False

        liquidations_input = liquidations if needs_liquidations else None

        try:
            start_perf = time.perf_counter()
            instance = cls()
            instance.parameters = cls.get_default_parameters()

            if required_ids:
                indicator_series: IndicatorSeriesInput = {}
                for dependency_id in required_ids:
                    dependency_cls = self._indicator_class_by_id.get(dependency_id)
                    if dependency_cls is None:
                        logger.warning("Composite %s: missing dependency %s", indicator_id, dependency_id)
                        continue
                    try:
                        dependency = dependency_cls()
                        dependency.parameters = dependency_cls.get_default_parameters()
                        dependency_series, _ = dependency.compute(
                            candles,
                            timeframe,
                            liquidations=liquidations_input,
                        )
                        if dependency_series:
                            indicator_series[dependency_id] = dependency_series
                    except Exception as exc:
                        logger.warning(
                            "Composite %s: dependency %s failed: %s",
                            indicator_id,
                            dependency_id,
                            exc,
                        )
                if len(indicator_series) < len(required_ids):
                    logger.warning(
                        "Composite %s: only %d/%d dependencies available",
                        indicator_id,
                        len(indicator_series),
                        len(required_ids),
                    )
                series, _ = instance.compute(
                    [],
                    timeframe,
                    liquidations=liquidations_input,
                    indicator_series=indicator_series,
                )
            else:
                series, _ = instance.compute(candles, timeframe, liquidations=liquidations_input)

            logger.debug("[IND] %s: %.3fs", indicator_id, time.perf_counter() - start_perf)
        except Exception as exc:
            logger.exception("Indicator %s failed: %s", indicator_id, exc)
            panel.clear("Indicator calculation failed. Check logs.")
            return False

        if not series:
            panel.clear("Not enough data for this indicator yet.")
            return False

        overlay_config = REGIME_OVERLAY_CONFIG.get(indicator_id)
        if overlay_config is not None:
            primary_series_key, low_key, high_key = overlay_config
            primary_series = series.get(primary_series_key) or []
            filtered_series = {primary_series_key: primary_series}
            regime_points = [(int(ts), float(value)) for ts, value in primary_series]
            low_threshold = float(self._config.get(low_key, 0.35))
            high_threshold = float(self._config.get(high_key, 0.65))
            price_points, highlight_bands = _build_regime_price_overlay(
                candles,
                regime_points,
                low_threshold,
                high_threshold,
            )
            panel.set_data(
                filtered_series,
                price_series=price_points,
                price_label="Close",
                highlight_bands=highlight_bands,
            )
        else:
            panel.set_data(series)
        return True

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._layout_restored:
            return

        self._layout_restored = True
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        geometry = settings.value("layout/geometry")
        if geometry is None:
            return

        try:
            if isinstance(geometry, bytes):
                geometry = QByteArray(geometry)
            self.restoreGeometry(geometry)

            screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
            if screen is not None:
                available = screen.availableGeometry()
                if not available.intersects(self.frameGeometry()):
                    self.move(available.topLeft())
        except Exception as exc:
            logger.debug("Restore geometry failed: %s", exc)

    def closeEvent(self, event) -> None:
        self._save_layout()
        self._config["date_range_days"] = self._date_range_days
        save_config(self._config)
        self._stop_services()
        event.accept()
