"""
Main window: dark theme, menu (Indicators, DateRange, Settings, Help), dock layout, persistence.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Type

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QMenu,
    QMenuBar,
    QTabWidget,
    QDialog,
    QMessageBox,
    QApplication,
    QLabel,
    QScrollArea,
    QFrame,
)
from PySide6.QtCore import QSettings, Qt, QTimer, Signal, QUrl, QByteArray
from PySide6.QtGui import QAction, QDesktopServices

from app.config import load_config, save_config, get_db_path, ensure_storage_dir, get_custom_indicators_dir
from app.storage.db import Database
from app.ingestion.candle_service import CandleIngestionService
from app.ingestion.liquidation_client import LiquidationClient
from app.indicators import discover_indicators
from app.indicators.base import IndicatorBase, IndicatorSeriesInput
from app.ui.theme import STYLESHEET, TEXT
from app.ui.chart_panel import ChartPanel
from app.ui.candlestick_panel import CandlestickPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.date_range_dialog import DateRangeDialog
try:
    from app.ui.surface3d_window import Surface3DWindow
except Exception:
    Surface3DWindow = None  # type: ignore

logger = logging.getLogger(__name__)

SETTINGS_ORG = "MarketMetrics"
SETTINGS_APP = "MarketMetrics"
INDICATOR_PANELS_KEY = "layout/indicator_panels"  # {indicator_id: {"tf": "1m"}}
CANDLESTICK_KEY = "layout/candlestick"  # {"tf": "1m"}
CENTRAL_TAB_INDEX_KEY = "layout/central_tab_index"


class MainWindow(QMainWindow):
    # Emit from worker thread; slot runs on main thread (do not touch widgets in on_progress).
    candle_progress = Signal(str)
    # Emitted when retention thread finishes (so UI can stay responsive during prune).
    retention_done = Signal()

    def __init__(self):
        super().__init__()
        print("MainWindow: init start", flush=True)
        self.setWindowTitle("MarketMetrics")
        self.candle_progress.connect(self._on_candle_progress)
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(900, 600)
        self.resize(1200, 700)

        self._config = load_config()
        print("MainWindow: config loaded", flush=True)
        ensure_storage_dir(self._config.get("storage_path") or "")
        db_path = get_db_path(self._config)
        self._db = Database(db_path)
        self._candle_service: Optional[CandleIngestionService] = None
        self._liquidation_client: Optional[LiquidationClient] = None

        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._project_indicators_dir = os.path.join(_project_root, "indicators")
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
        print("MainWindow: indicators discovered", flush=True)
        self._indicator_classes: List[Type[IndicatorBase]] = classes
        self._indicator_actions: Dict[str, QAction] = {}
        self._indicator_class_by_id: Dict[str, Type[IndicatorBase]] = {c.id: c for c in self._indicator_classes}
        self._date_range_days = int(self._config.get("date_range_days", 90))
        self._surface3d_window: Optional[Any] = None  # standalone 3D window
        self._candlestick_panel: Optional[CandlestickPanel] = None
        self._central_tabs: Optional[QTabWidget] = None
        # indicator_id -> ChartPanel (all in central tab widget, fill center space)
        self._indicator_panels: Dict[str, ChartPanel] = {}
        self._layout_restored = False

        self._build_central_tabs()  # Candlestick + all indicators in center, fill space
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_all_indicators)
        self._refresh_timer.start(60 * 1000)  # refresh charts every 60s
        # Defer menus + layout + retention + services so window can show first (avoids hang on menu/QSettings)
        QTimer.singleShot(0, self._deferred_startup)
        print("MainWindow: init done", flush=True)

    def _deferred_startup(self) -> None:
        """Run after first event loop tick: menus, layout, services; retention in background."""
        print("MainWindow: deferred startup (menus, layout, services)...", flush=True)
        self._build_menus()
        self._restore_layout_only_tf_and_tab()
        self._start_services()
        # Run retention (DB prune) in background so UI stays responsive
        self.retention_done.connect(self._on_retention_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(target=self._run_retention_in_thread, daemon=True)
        thread.start()
        print("MainWindow: deferred startup done (retention running in background)", flush=True)

    def _run_retention_in_thread(self) -> None:
        """Called from background thread: run retention then signal main thread."""
        try:
            self._apply_retention()
        except Exception as e:
            logger.exception("Retention failed: %s", e)
        self.retention_done.emit()

    def _on_retention_done(self) -> None:
        """Slot: run on main thread after retention finishes; schedule first refresh."""
        try:
            self.retention_done.disconnect(self._on_retention_done)
        except Exception:
            pass
        QTimer.singleShot(500, self._refresh_all_indicators)

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        self._indicators_menu = QMenu("Indicators", self)
        menubar.addMenu(self._indicators_menu)
        self._rebuild_indicators_menu()

        dr_menu = menubar.addMenu("Date Range")
        dr_action = QAction("Set date range...", self)
        dr_action.triggered.connect(self._open_date_range)
        dr_menu.addAction(dr_action)

        st_menu = menubar.addMenu("Settings")
        settings_action = QAction("Settings...", self)
        settings_action.triggered.connect(self._open_settings)
        st_menu.addAction(settings_action)

        help_menu = menubar.addMenu("Help")
        help_action = QAction("About", self)
        help_action.triggered.connect(self._show_about)
        help_menu.addAction(help_action)

    def _build_central_tabs(self) -> None:
        """Central tab widget: Candlestick + all indicators. Each tab fills the center space."""
        tabs = QTabWidget(self)
        tabs.setDocumentMode(True)
        # Candlestick first
        candlestick = CandlestickPanel(self)
        candlestick.timeframe_changed.connect(self._refresh_all_indicators)
        self._candlestick_panel = candlestick
        tabs.addTab(candlestick, "Candlestick")
        # Then one tab per indicator
        for cls in self._indicator_classes:
            if cls.id in self._indicator_panels:
                continue
            panel = ChartPanel(cls.id, cls.display_name, self)
            panel.timeframe_changed.connect(self._refresh_all_indicators)
            self._indicator_panels[cls.id] = panel
            tabs.addTab(panel, cls.display_name)
        self._central_tabs = tabs
        self.setCentralWidget(tabs)
        print("MainWindow: central tabs built", flush=True)

    def _restore_layout_only_tf_and_tab(self) -> None:
        """Restore TF and tab index from settings (no geometry; that is in showEvent)."""
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        candlestick_json = settings.value(CANDLESTICK_KEY)
        if candlestick_json and self._candlestick_panel is not None:
            try:
                data = json.loads(candlestick_json) if isinstance(candlestick_json, str) else candlestick_json
                if isinstance(data, dict):
                    tf = data.get("tf", "1m")
                    self._candlestick_panel.set_timeframe(tf)
            except Exception:
                pass
        panels_json = settings.value(INDICATOR_PANELS_KEY)
        if panels_json:
            try:
                data = json.loads(panels_json) if isinstance(panels_json, str) else panels_json
                for indicator_id, cfg in (data.items() if isinstance(data, dict) else []):
                    panel = self._indicator_panels.get(indicator_id)
                    if panel is not None and isinstance(cfg, dict):
                        tf = cfg.get("tf", "1m")
                        panel.set_timeframe(tf)
            except Exception:
                pass
        tab_index = settings.value(CENTRAL_TAB_INDEX_KEY)
        if tab_index is not None and self._central_tabs is not None:
            try:
                idx = int(tab_index)
                if 0 <= idx < self._central_tabs.count():
                    self._central_tabs.setCurrentIndex(idx)
            except (ValueError, TypeError):
                pass

    def _rebuild_indicators_menu(self) -> None:
        """Indicators menu: switch to Candlestick or indicator tab; Vol Stability 3D, Reload, Open Folder."""
        self._indicators_menu.clear()
        self._indicator_actions.clear()
        if self._central_tabs is None or self._candlestick_panel is None:
            return
        # Candlestick: switch to its tab (always first)
        candlestick_action = QAction("Candlestick", self)
        candlestick_action.triggered.connect(self._show_candlestick_tab)
        self._indicators_menu.addAction(candlestick_action)
        self._indicators_menu.addSeparator()
        # One action per indicator: switch to that tab by panel
        for cls in self._indicator_classes:
            action = QAction(cls.display_name, self)
            action.triggered.connect(lambda checked=False, id=cls.id: self._show_indicator_tab(id))
            self._indicators_menu.addAction(action)
            self._indicator_actions[cls.id] = action
        if Surface3DWindow is not None:
            self._indicators_menu.addSeparator()
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

    def _show_candlestick_tab(self) -> None:
        """Switch central tab to Candlestick."""
        if self._central_tabs is not None and self._candlestick_panel is not None:
            idx = self._central_tabs.indexOf(self._candlestick_panel)
            if idx >= 0:
                self._central_tabs.setCurrentIndex(idx)

    def _show_indicator_tab(self, indicator_id: str) -> None:
        """Switch central tab to the indicator panel for indicator_id."""
        if self._central_tabs is None:
            return
        panel = self._indicator_panels.get(indicator_id)
        if panel is not None:
            idx = self._central_tabs.indexOf(panel)
            if idx >= 0:
                self._central_tabs.setCurrentIndex(idx)

    def _reload_indicators(self) -> None:
        """Re-scan plugin dirs, reload modules, rebuild central tabs and menu. Runs on UI thread."""
        classes, errors = discover_indicators(
            self._project_indicators_dir,
            self._custom_indicators_dir,
            self._composite_indicators_dir,
            reload_plugins=True,
        )
        for err in errors:
            logger.warning("Indicator reload: %s", err)
        if errors:
            self.statusBar().showMessage(
                f"Indicator reload: {len(errors)} failed (see log)",
                8000,
            )
        else:
            self.statusBar().showMessage("Indicators reloaded", 3000)
        self._indicator_classes = classes
        self._indicator_class_by_id = {c.id: c for c in self._indicator_classes}
        # Remove tabs for removed indicators; keep candlestick and existing panels
        if self._central_tabs is not None:
            for indicator_id in list(self._indicator_panels.keys()):
                if indicator_id not in self._indicator_class_by_id:
                    panel = self._indicator_panels[indicator_id]
                    idx = self._central_tabs.indexOf(panel)
                    if idx >= 0:
                        self._central_tabs.removeTab(idx)
                    panel.deleteLater()
                    del self._indicator_panels[indicator_id]
        # Add tabs for new indicators
        for cls in self._indicator_classes:
            if cls.id not in self._indicator_panels and self._central_tabs is not None:
                panel = ChartPanel(cls.id, cls.display_name, self)
                panel.timeframe_changed.connect(self._refresh_all_indicators)
                self._indicator_panels[cls.id] = panel
                self._central_tabs.addTab(panel, cls.display_name)
        self._rebuild_indicators_menu()
        self._refresh_all_indicators()

    def _open_indicators_folder(self) -> None:
        """Open custom indicators directory in system file manager."""
        path = self._custom_indicators_dir
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        url = QUrl.fromLocalFile(path)
        if not QDesktopServices.openUrl(url):
            self.statusBar().showMessage(f"Could not open: {path}", 5000)

    def _open_vol_stability_window(self) -> None:
        """Open standalone 3D surface window; bring to front if already open."""
        if Surface3DWindow is None:
            return
        if self._surface3d_window is not None and self._surface3d_window.isVisible():
            self._surface3d_window.raise_()
            self._surface3d_window.activateWindow()
            return
        if self._surface3d_window is not None:
            self._surface3d_window.deleteLater()
            self._surface3d_window = None
        symbol = self._config.get("symbol", "BTCUSDT")
        lookback_hours = self._date_range_days * 24
        win = Surface3DWindow(
            self._db,
            symbol=symbol,
            lookback_hours=lookback_hours,
            parent=None,
        )
        win.setAttribute(Qt.WA_DeleteOnClose)
        win.destroyed.connect(lambda: setattr(self, "_surface3d_window", None))
        self._surface3d_window = win
        win.show()

    def _restore_layout(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        # Candlestick TF
        candlestick_json = settings.value(CANDLESTICK_KEY)
        if candlestick_json and self._candlestick_panel is not None:
            try:
                data = json.loads(candlestick_json) if isinstance(candlestick_json, str) else candlestick_json
                if isinstance(data, dict):
                    tf = data.get("tf", "1m")
                    self._candlestick_panel.set_timeframe(tf)
            except Exception:
                pass
        # TF per indicator
        panels_json = settings.value(INDICATOR_PANELS_KEY)
        if panels_json:
            try:
                data: Dict[str, Dict[str, str]] = json.loads(panels_json) if isinstance(panels_json, str) else panels_json
                for indicator_id, cfg in data.items():
                    panel = self._indicator_panels.get(indicator_id)
                    if panel is not None and isinstance(cfg, dict):
                        tf = cfg.get("tf", "1m")
                        panel.set_timeframe(tf)
            except Exception:
                pass
        # Central tab index (which indicator is in center)
        tab_index = settings.value(CENTRAL_TAB_INDEX_KEY)
        if tab_index is not None and self._central_tabs is not None:
            try:
                idx = int(tab_index)
                if 0 <= idx < self._central_tabs.count():
                    self._central_tabs.setCurrentIndex(idx)
            except (ValueError, TypeError):
                pass
        # Geometry restored in showEvent() so window is fully initialized (avoids off-screen / no-show)

    def _save_layout(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        if self._candlestick_panel is not None:
            candlestick_data = {"tf": self._candlestick_panel.get_timeframe()}
            settings.setValue(CANDLESTICK_KEY, json.dumps(candlestick_data))
        panels_data: Dict[str, Dict[str, str]] = {}
        for indicator_id, panel in self._indicator_panels.items():
            if panel is not None:
                panels_data[indicator_id] = {"tf": panel.get_timeframe()}
        settings.setValue(INDICATOR_PANELS_KEY, json.dumps(panels_data))
        if self._central_tabs is not None:
            settings.setValue(CENTRAL_TAB_INDEX_KEY, self._central_tabs.currentIndex())
        settings.setValue("layout/geometry", self.saveGeometry())

    def _open_date_range(self) -> None:
        dlg = DateRangeDialog(self._date_range_days, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_range_days = dlg.get_days()
            self._config["date_range_days"] = self._date_range_days
            save_config(self._config)
            lookback_hours = self._date_range_days * 24
            if self._surface3d_window is not None and self._surface3d_window.isVisible():
                self._surface3d_window.set_lookback_hours(lookback_hours)
            self._refresh_all_indicators()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            save_config(self._config)
            self._apply_retention()
            # Restart candle/liquidation services so new candle_start_date and ngrok take effect
            self._stop_services()
            self._start_services()
            self.statusBar().showMessage("Settings saved. Candle download restarted with new options.", 5000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About MarketMetrics",
            "MarketMetrics — Docking desktop app for candles, liquidations, and indicators.\n\nDark theme only.",
        )

    def _apply_retention(self) -> None:
        mode = self._config.get("retention_mode", "days")
        if mode == "days":
            keep = int(self._config.get("retention_days", 90))
            self._db.prune_by_days(keep)
        else:
            max_gb = float(self._config.get("retention_size_gb", 5.0))
            self._db.prune_by_size_gb(max_gb)

    def _on_candle_progress(self, msg: str) -> None:
        """Slot: runs on main thread; safe to update UI."""
        self.statusBar().showMessage(msg)

    def _start_services(self) -> None:
        symbol = self._config.get("symbol", "BTCUSDT")
        poll = float(self._config.get("candle_poll_interval_sec", 60))
        # Pass callback that emits signal so UI is updated on main thread only.
        start_date = (self._config.get("candle_start_date") or "").strip()
        self._candle_service = CandleIngestionService(
            self._db,
            symbol,
            poll_interval_sec=poll,
            on_progress=lambda m: self.candle_progress.emit(m),
            start_date=start_date or None,
        )
        self._candle_service.start()
        ngrok = (self._config.get("ngrok_liquidations_url") or "").strip()
        if ngrok:
            reconnect = float(self._config.get("liquidations_reconnect_delay_sec", 5))
            self._liquidation_client = LiquidationClient(
                self._db, ngrok, symbol=symbol, reconnect_delay_sec=reconnect
            )
            self._liquidation_client.start()

    def _stop_services(self) -> None:
        if self._candle_service:
            self._candle_service.stop()
            self._candle_service = None
        if self._liquidation_client:
            self._liquidation_client.stop()
            self._liquidation_client = None

    def _refresh_all_indicators(self) -> None:
        symbol = self._config.get("symbol", "BTCUSDT")
        days_ms = self._date_range_days * 24 * 60 * 60 * 1000
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - days_ms
        liquidations = self._db.get_liquidations_1m(symbol, start_ms, end_ms) if symbol else []
        # Refresh candlestick panel: use native DB table for selected TF (1m, 5m, 15m, 1h), not resampled from 1m
        if self._candlestick_panel is not None:
            try:
                tf = self._candlestick_panel.get_timeframe()
                candles = self._db.get_candles(symbol, tf, start_ms, end_ms)
                if candles:
                    self._candlestick_panel.set_data(candles)
            except Exception as e:
                logger.exception("Candlestick panel failed: %s", e)
        for indicator_id, panel in self._indicator_panels.items():
            if panel is None:
                continue
            cls = self._indicator_class_by_id.get(indicator_id)
            if not cls:
                continue
            tf = panel.get_timeframe()
            if tf == "1m":
                candles = self._db.get_candles_1m(symbol, start_ms, end_ms)
            else:
                candles = self._db.resample_candles(symbol, start_ms, end_ms, tf)
            if not candles and "liquidations" not in [x.get("name") for x in cls.required_inputs]:
                continue
            liq = liquidations if any(x.get("name") == "liquidations" for x in cls.required_inputs) else None
            try:
                inst = cls()
                inst.parameters = cls.get_default_parameters()
                required_ids = getattr(cls, "required_indicator_ids", None) or []
                if required_ids:
                    indicator_series: IndicatorSeriesInput = {}
                    for dep_id in required_ids:
                        dep_cls = self._indicator_class_by_id.get(dep_id)
                        if dep_cls is None:
                            logger.warning("Composite %s: missing dependency %s", indicator_id, dep_id)
                            continue
                        try:
                            dep_inst = dep_cls()
                            dep_inst.parameters = dep_cls.get_default_parameters()
                            dep_series, _ = dep_inst.compute(candles, tf, liquidations=liq)
                            if dep_series:
                                indicator_series[dep_id] = dep_series
                        except Exception as e:
                            logger.warning("Composite %s: dependency %s failed: %s", indicator_id, dep_id, e)
                    if len(indicator_series) < len(required_ids):
                        logger.warning("Composite %s: only %d/%d dependencies available", indicator_id, len(indicator_series), len(required_ids))
                    series, _ = inst.compute([], tf, liquidations=liq, indicator_series=indicator_series)
                else:
                    series, _ = inst.compute(candles, tf, liquidations=liq)
                if series:
                    panel.set_data(series)
            except Exception as e:
                logger.exception("Indicator %s failed: %s", indicator_id, e)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._layout_restored:
            self._layout_restored = True
            settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
            geometry = settings.value("layout/geometry")
            if geometry is not None:
                try:
                    if isinstance(geometry, bytes):
                        geometry = QByteArray(geometry)
                    self.restoreGeometry(geometry)
                    # Ensure window is on a visible screen (e.g. after monitor change)
                    screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
                    if screen is not None:
                        sr = screen.availableGeometry()
                        if not sr.intersects(self.frameGeometry()):
                            self.move(sr.topLeft())
                except Exception as e:
                    logger.debug("Restore geometry failed: %s", e)

    def closeEvent(self, event) -> None:
        self._save_layout()
        self._config["date_range_days"] = self._date_range_days
        save_config(self._config)
        self._stop_services()
        event.accept()
