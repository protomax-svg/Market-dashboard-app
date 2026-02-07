"""
DateRange: how much history to display (days). Does not change stored data.
"""
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QSpinBox,
    QPushButton,
    QHBoxLayout,
)
from PySide6.QtCore import Qt

from app.ui.theme import STYLESHEET


class DateRangeDialog(QDialog):
    def __init__(self, current_days: int = 30, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Date Range")
        self.setStyleSheet(STYLESHEET)
        self._days = current_days
        layout = QVBoxLayout(self)
        fl = QFormLayout()
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 365)
        self.days_spin.setValue(current_days)
        self.days_spin.setSuffix(" days")
        fl.addRow("Display history:", self.days_spin)
        layout.addLayout(fl)
        btns = QHBoxLayout()
        btns.addStretch()
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

    def get_days(self) -> int:
        return self.days_spin.value()
