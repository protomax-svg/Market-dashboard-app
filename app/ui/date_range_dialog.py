"""
Date range dialog: controls how much history the charts display.
"""
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from app.ui.theme import STYLESHEET


class DateRangeDialog(QDialog):
    def __init__(self, current_days: int = 90, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Date Range")
        self.setStyleSheet(STYLESHEET)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "This changes the visible history window for the charts. Stored data on disk is not deleted."
        )
        hint.setObjectName("DialogHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.days_spin = QSpinBox()
        self.days_spin.setRange(1, 36500)
        self.days_spin.setValue(current_days)
        self.days_spin.setSuffix(" days")
        form.addRow("Display history", self.days_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_days(self) -> int:
        return self.days_spin.value()
