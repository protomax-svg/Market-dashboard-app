"""
Settings dialog: symbol, storage path, retention, liquidation source, and candle ingestion.
"""
from datetime import datetime
from typing import Any, Dict

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from app.config import DEFAULT_STORAGE_PATH
from app.ui.theme import STYLESHEET


class SettingsDialog(QDialog):
    def __init__(self, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(560)
        self.config = dict(config)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Tune data ingestion and storage behavior. Changes apply immediately after you save."
        )
        intro.setObjectName("DialogHint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        g_data = QGroupBox("Market")
        market_form = QFormLayout(g_data)

        self.symbol_edit = QLineEdit(self.config.get("symbol", "BTCUSDT"))
        self.symbol_edit.setPlaceholderText("e.g. BTCUSDT")
        market_form.addRow("Symbol", self.symbol_edit)

        self.storage_edit = QLineEdit(self.config.get("storage_path") or DEFAULT_STORAGE_PATH)
        self.storage_edit.setPlaceholderText(DEFAULT_STORAGE_PATH)
        market_form.addRow("Storage path", self.storage_edit)

        tf_hint = QLabel("Chart panels currently support 5m, 15m, and 1h timeframes.")
        tf_hint.setObjectName("DialogHint")
        tf_hint.setWordWrap(True)
        market_form.addRow("Timeframes", tf_hint)
        layout.addWidget(g_data)

        g_layout = QGroupBox("Dashboard")
        layout_form = QFormLayout(g_layout)

        self.show_balanced_regime_panel = QCheckBox("Replace lower indicator strip with Balanced Regime Index chart")
        self.show_balanced_regime_panel.setChecked(bool(self.config.get("show_balanced_regime_panel", True)))
        layout_form.addRow("Bottom area", self.show_balanced_regime_panel)

        layout_hint = QLabel(
            "When enabled, the compact indicator strip is hidden and replaced by a second large regime-style chart."
        )
        layout_hint.setObjectName("DialogHint")
        layout_hint.setWordWrap(True)
        layout_form.addRow("", layout_hint)
        layout.addWidget(g_layout)

        g_retention = QGroupBox("Retention")
        retention_form = QFormLayout(g_retention)

        self.retention_mode = QComboBox()
        self.retention_mode.addItems(["By days", "By size (GB)"])
        mode = self.config.get("retention_mode", "days")
        self.retention_mode.setCurrentIndex(1 if mode == "size_gb" else 0)
        self.retention_mode.currentIndexChanged.connect(self._sync_retention_fields)
        retention_form.addRow("Mode", self.retention_mode)

        self.retention_days = QSpinBox()
        self.retention_days.setRange(1, 3650)
        self.retention_days.setValue(int(self.config.get("retention_days", 90)))
        retention_form.addRow("Keep days", self.retention_days)

        self.retention_size_gb = QDoubleSpinBox()
        self.retention_size_gb.setRange(0.1, 100.0)
        self.retention_size_gb.setDecimals(1)
        self.retention_size_gb.setValue(float(self.config.get("retention_size_gb", 5.0)))
        retention_form.addRow("Max size (GB)", self.retention_size_gb)
        layout.addWidget(g_retention)

        g_liq = QGroupBox("Liquidations")
        liq_form = QFormLayout(g_liq)

        self.ngrok_url = QLineEdit(self.config.get("ngrok_liquidations_url", ""))
        self.ngrok_url.setPlaceholderText("https://your-endpoint.example.com")
        liq_form.addRow("Endpoint URL", self.ngrok_url)

        self.reconnect_delay = QSpinBox()
        self.reconnect_delay.setRange(1, 120)
        self.reconnect_delay.setValue(int(self.config.get("liquidations_reconnect_delay_sec", 5)))
        liq_form.addRow("Reconnect delay (s)", self.reconnect_delay)
        layout.addWidget(g_liq)

        g_candle = QGroupBox("Candles")
        candle_form = QFormLayout(g_candle)

        self.candle_start_date = QLineEdit(self.config.get("candle_start_date", ""))
        self.candle_start_date.setPlaceholderText("YYYY-MM-DD")
        candle_form.addRow("Download from date", self.candle_start_date)

        candle_hint = QLabel(
            "Leave the date empty to match the current chart range. "
            "Set an explicit date such as 2022-01-01 to keep deeper 1h history; "
            "long backfills start with 1h, then fill finer candles where available."
        )
        candle_hint.setObjectName("DialogHint")
        candle_hint.setWordWrap(True)
        candle_form.addRow("", candle_hint)

        self.candle_poll = QSpinBox()
        self.candle_poll.setRange(10, 600)
        self.candle_poll.setValue(int(self.config.get("candle_poll_interval_sec", 60)))
        candle_form.addRow("Poll interval (s)", self.candle_poll)
        layout.addWidget(g_candle)

        g_regime = QGroupBox("Regime Index")
        regime_form = QFormLayout(g_regime)

        self.regime_highlight_low = QDoubleSpinBox()
        self.regime_highlight_low.setRange(0.0, 1.0)
        self.regime_highlight_low.setDecimals(2)
        self.regime_highlight_low.setSingleStep(0.05)
        self.regime_highlight_low.setValue(float(self.config.get("regime_highlight_low", 0.35)))
        regime_form.addRow("Low highlight", self.regime_highlight_low)

        self.regime_highlight_high = QDoubleSpinBox()
        self.regime_highlight_high.setRange(0.0, 1.0)
        self.regime_highlight_high.setDecimals(2)
        self.regime_highlight_high.setSingleStep(0.05)
        self.regime_highlight_high.setValue(float(self.config.get("regime_highlight_high", 0.65)))
        regime_form.addRow("High highlight", self.regime_highlight_high)

        regime_hint = QLabel(
            "The Regime chart will paint green price zones below the low level and red price zones above the high level."
        )
        regime_hint.setObjectName("DialogHint")
        regime_hint.setWordWrap(True)
        regime_form.addRow("", regime_hint)
        layout.addWidget(g_regime)

        g_balanced_regime = QGroupBox("Balanced Regime Index")
        balanced_regime_form = QFormLayout(g_balanced_regime)

        self.balanced_regime_highlight_low = QDoubleSpinBox()
        self.balanced_regime_highlight_low.setRange(0.0, 1.0)
        self.balanced_regime_highlight_low.setDecimals(2)
        self.balanced_regime_highlight_low.setSingleStep(0.05)
        self.balanced_regime_highlight_low.setValue(float(self.config.get("balanced_regime_highlight_low", 0.35)))
        balanced_regime_form.addRow("Low highlight", self.balanced_regime_highlight_low)

        self.balanced_regime_highlight_high = QDoubleSpinBox()
        self.balanced_regime_highlight_high.setRange(0.0, 1.0)
        self.balanced_regime_highlight_high.setDecimals(2)
        self.balanced_regime_highlight_high.setSingleStep(0.05)
        self.balanced_regime_highlight_high.setValue(float(self.config.get("balanced_regime_highlight_high", 0.65)))
        balanced_regime_form.addRow("High highlight", self.balanced_regime_highlight_high)

        balanced_regime_hint = QLabel(
            "Balanced Regime paints green price zones below the low level and red price zones above the high level."
        )
        balanced_regime_hint.setObjectName("DialogHint")
        balanced_regime_hint.setWordWrap(True)
        balanced_regime_form.addRow("", balanced_regime_hint)
        layout.addWidget(g_balanced_regime)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._sync_retention_fields()

    def _sync_retention_fields(self) -> None:
        by_days = self.retention_mode.currentIndex() == 0
        self.retention_days.setEnabled(by_days)
        self.retention_size_gb.setEnabled(not by_days)

    def accept(self) -> None:
        start_date = self.candle_start_date.text().strip()
        if start_date:
            try:
                datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid Date",
                    "Use YYYY-MM-DD for the candle start date, or leave it empty.",
                )
                self.candle_start_date.setFocus()
                return
        if self.regime_highlight_low.value() >= self.regime_highlight_high.value():
            QMessageBox.warning(
                self,
                "Invalid Regime Levels",
                "Regime low highlight must be smaller than the high highlight level.",
            )
            self.regime_highlight_low.setFocus()
            return
        if self.balanced_regime_highlight_low.value() >= self.balanced_regime_highlight_high.value():
            QMessageBox.warning(
                self,
                "Invalid Balanced Regime Levels",
                "Balanced Regime low highlight must be smaller than the high highlight level.",
            )
            self.balanced_regime_highlight_low.setFocus()
            return
        super().accept()

    def get_config(self) -> Dict[str, Any]:
        out = dict(self.config)
        out["symbol"] = self.symbol_edit.text().strip().upper() or "BTCUSDT"
        out["storage_path"] = self.storage_edit.text().strip() or DEFAULT_STORAGE_PATH
        out["retention_mode"] = "size_gb" if self.retention_mode.currentIndex() == 1 else "days"
        out["retention_days"] = self.retention_days.value()
        out["retention_size_gb"] = self.retention_size_gb.value()
        out["ngrok_liquidations_url"] = self.ngrok_url.text().strip()
        out["liquidations_reconnect_delay_sec"] = self.reconnect_delay.value()
        out["candle_start_date"] = self.candle_start_date.text().strip()
        out["candle_poll_interval_sec"] = self.candle_poll.value()
        out["regime_highlight_low"] = self.regime_highlight_low.value()
        out["regime_highlight_high"] = self.regime_highlight_high.value()
        out["balanced_regime_highlight_low"] = self.balanced_regime_highlight_low.value()
        out["balanced_regime_highlight_high"] = self.balanced_regime_highlight_high.value()
        out["show_balanced_regime_panel"] = self.show_balanced_regime_panel.isChecked()
        return out
