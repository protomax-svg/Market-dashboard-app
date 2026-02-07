"""
Main window: dark theme, menu (Indicators, DateRange, Settings, Help), dock layout, persistence.
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Type

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QMenu,
    QMenuBar,
    QDockWidget,
    QDialog,
    QMessageBox,
    QApplication,
    QLabel,
    QScrollArea,
    QFrame,
)
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction

from app.config import load_config, save_config, get_db_path, ensure_storage_dir
from app.storage.db import Database
from app.ingestion.candle_service import CandleIngestionService
from app.ingestion.liquidation_client import LiquidationClient
from app.indicators import discover_indicators
from app.indicators.base import IndicatorBase
from app.ui.theme import STYLESHEET, MUTED
from app.ui.chart_panel import ChartPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.date_range_dialog import DateRangeDialog

logger = logging.getLogger(__name__)

SETTINGS_ORG = "MarketMetrics"
SETTINGS_APP = "MarketMetrics"
INDICATORS_VISIBLE_KEY = "layout/indicators_visible"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MarketMetrics")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumSize(900, 600)
        self.resize(1200, 700)

        self._config = load_config()
        ensure_storage_dir(self._config.get("storage_path") or "")
        db_path = get_db_path(self._config)
        self._db = Database(db_path)
        self._candle_service: Optional[CandleIngestionService] = None
        self._liquidation_client: Optional[LiquidationClient] = None

        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _indicators_extra = os.path.join(_project_root, "indicators")
        self._indicator_classes: List[Type[IndicatorBase]] = discover_indicators(_indicators_extra)
        self._dock_widgets: Dict[str, QDockWidget] = {}
        self._chart_panels: Dict[str, ChartPanel] = {}
        self._indicator_actions: Dict[str, QAction] = {}
        self._date_range_days = int(self._config.get("date_range_days", 30))

        self._build_menus()
        self._build_central_placeholder()
        self._build_docks()
        self._restore_layout()
        self._apply_retention()
        self._start_services()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_all_indicators)
        self._refresh_timer.start(60 * 1000)  # refresh charts every 60s
        QTimer.singleShot(2000, self._refresh_all_indicators)

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        # Indicators menu: list with checkboxes
        self._indicators_menu = QMenu("Indicators", self)
        menubar.addMenu(self._indicators_menu)
        for cls in self._indicator_classes:
            action = QAction(cls.display_name, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.triggered.connect(lambda checked, c=cls: self._toggle_indicator(c.id, checked))
            self._indicators_menu.addAction(action)
            self._indicator_actions[cls.id] = action

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

    def _build_central_placeholder(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        label = QLabel("Charts appear in dock panels. Use Indicators menu to show/hide.")
        label.setStyleSheet(f"color: {MUTED}; padding: 20px;")
        layout.addWidget(label)
        self.setCentralWidget(central)

    def _build_docks(self) -> None:
        for cls in self._indicator_classes:
            panel = ChartPanel(cls.id, cls.display_name, self)
            dock = QDockWidget(cls.display_name, self)
            dock.setWidget(panel)
            dock.setObjectName(f"dock_{cls.id}")
            self.addDockWidget(Qt.RightDockWidgetArea, dock)
            self._dock_widgets[cls.id] = dock
            self._chart_panels[cls.id] = panel

    def _restore_layout(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        visible = settings.value(INDICATORS_VISIBLE_KEY)
        if visible is not None:
            try:
                ids: List[str] = json.loads(visible) if isinstance(visible, str) else visible
                for iid, action in self._indicator_actions.items():
                    action.setChecked(iid in ids)
                for iid, dock in self._dock_widgets.items():
                    dock.setVisible(iid in ids)
            except Exception:
                pass
        state = settings.value("layout/dockState")
        if state is not None:
            try:
                self.restoreState(state)
            except Exception:
                pass
        geometry = settings.value("layout/geometry")
        if geometry is not None:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass

    def _save_layout(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        visible = [iid for iid, a in self._indicator_actions.items() if a.isChecked()]
        settings.setValue(INDICATORS_VISIBLE_KEY, json.dumps(visible))
        settings.setValue("layout/dockState", self.saveState())
        settings.setValue("layout/geometry", self.saveGeometry())

    def _toggle_indicator(self, indicator_id: str, visible: bool) -> None:
        if indicator_id in self._dock_widgets:
            self._dock_widgets[indicator_id].setVisible(visible)

    def _open_date_range(self) -> None:
        dlg = DateRangeDialog(self._date_range_days, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._date_range_days = dlg.get_days()
            self._config["date_range_days"] = self._date_range_days
            save_config(self._config)
            self._refresh_all_indicators()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.get_config()
            save_config(self._config)
            self._apply_retention()
            # Restart services with new config would require stopping/starting
            QMessageBox.information(
                self,
                "Settings",
                "Settings saved. Restart the app for symbol/ngrok changes to take effect.",
            )

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

    def _start_services(self) -> None:
        symbol = self._config.get("symbol", "BTCUSDT")
        poll = float(self._config.get("candle_poll_interval_sec", 60))
        self._candle_service = CandleIngestionService(self._db, symbol, poll_interval_sec=poll)
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
        for cls in self._indicator_classes:
            panel = self._chart_panels.get(cls.id)
            if not panel or not self._dock_widgets[cls.id].isVisible():
                continue
            # Determine required timeframe
            tf = "1m"
            for inp in cls.required_inputs:
                if inp.get("name") == "candles":
                    tf = inp.get("timeframe", "1m")
                    break
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
                series, _ = inst.compute(candles, tf, liquidations=liq)
                if series:
                    panel.set_data(series)
            except Exception as e:
                logger.exception("Indicator %s failed: %s", cls.id, e)

    def closeEvent(self, event) -> None:
        self._save_layout()
        self._config["date_range_days"] = self._date_range_days
        save_config(self._config)
        self._stop_services()
        event.accept()
