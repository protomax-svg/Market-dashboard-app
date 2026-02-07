"""
Settings dialog: symbol, timeframes, storage path, retention, ngrok URL.
"""
from typing import Any, Dict, List

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QPushButton,
    QGroupBox,
    QLabel,
)
from PySide6.QtCore import Qt

from app.ui.theme import STYLESHEET


class SettingsDialog(QDialog):
    def __init__(self, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setStyleSheet(STYLESHEET)
        self.config = dict(config)
        layout = QVBoxLayout(self)

        g_data = QGroupBox("Data")
        fl = QFormLayout(g_data)
        self.symbol_edit = QLineEdit(self.config.get("symbol", "BTCUSDT"))
        self.symbol_edit.setPlaceholderText("e.g. BTCUSDT")
        fl.addRow("Symbol:", self.symbol_edit)

        self.timeframes_edit = QLineEdit(",".join(self.config.get("timeframes_enabled", ["1m"])))
        self.timeframes_edit.setPlaceholderText("1m,5m,15m,1h")
        fl.addRow("Timeframes enabled:", self.timeframes_edit)

        self.storage_edit = QLineEdit(self.config.get("storage_path", ""))
        self.storage_edit.setPlaceholderText("Leave default for ~/.marketmetrics")
        fl.addRow("Storage path:", self.storage_edit)
        layout.addWidget(g_data)

        g_retention = QGroupBox("Retention")
        fl2 = QFormLayout(g_retention)
        self.retention_mode = QComboBox()
        self.retention_mode.addItems(["By days", "By size (GB)"])
        mode = self.config.get("retention_mode", "days")
        self.retention_mode.setCurrentIndex(1 if mode == "size_gb" else 0)
        fl2.addRow("Mode:", self.retention_mode)

        self.retention_days = QSpinBox()
        self.retention_days.setRange(1, 3650)
        self.retention_days.setValue(int(self.config.get("retention_days", 90)))
        fl2.addRow("Keep days:", self.retention_days)

        self.retention_size_gb = QDoubleSpinBox()
        self.retention_size_gb.setRange(0.1, 100.0)
        self.retention_size_gb.setValue(float(self.config.get("retention_size_gb", 5.0)))
        self.retention_size_gb.setDecimals(1)
        fl2.addRow("Max size (GB):", self.retention_size_gb)
        layout.addWidget(g_retention)

        g_liq = QGroupBox("Liquidations")
        fl3 = QFormLayout(g_liq)
        self.ngrok_url = QLineEdit(self.config.get("ngrok_liquidations_url", ""))
        self.ngrok_url.setPlaceholderText("https://xxxx.ngrok.io")
        fl3.addRow("Ngrok endpoint URL:", self.ngrok_url)

        self.reconnect_delay = QSpinBox()
        self.reconnect_delay.setRange(1, 120)
        self.reconnect_delay.setValue(int(self.config.get("liquidations_reconnect_delay_sec", 5)))
        fl3.addRow("Reconnect delay (s):", self.reconnect_delay)
        layout.addWidget(g_liq)

        g_candle = QGroupBox("Candles")
        fl4 = QFormLayout(g_candle)
        self.candle_poll = QSpinBox()
        self.candle_poll.setRange(10, 600)
        self.candle_poll.setValue(int(self.config.get("candle_poll_interval_sec", 60)))
        fl4.addRow("Poll interval (s):", self.candle_poll)
        layout.addWidget(g_candle)

        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def get_config(self) -> Dict[str, Any]:
        out = dict(self.config)
        out["symbol"] = self.symbol_edit.text().strip() or "BTCUSDT"
        tf_text = self.timeframes_edit.text().strip() or "1m"
        out["timeframes_enabled"] = [x.strip() for x in tf_text.split(",") if x.strip()]
        out["storage_path"] = self.storage_edit.text().strip() or None
        out["retention_mode"] = "size_gb" if self.retention_mode.currentIndex() == 1 else "days"
        out["retention_days"] = self.retention_days.value()
        out["retention_size_gb"] = self.retention_size_gb.value()
        out["ngrok_liquidations_url"] = self.ngrok_url.text().strip()
        out["liquidations_reconnect_delay_sec"] = self.reconnect_delay.value()
        out["candle_poll_interval_sec"] = self.candle_poll.value()
        return out
