"""
Light gray theme — neutral, easy on the eyes.
"""
# Background: light gray
BG_DARK = "#595959"
BG_MAIN = "#828282"
# Panels: slightly lighter
BG_PANEL = "#525252"
# Borders: medium gray
BORDER = "#303030"
# Text: dark gray (readable on light)
TEXT = "#bbbbbd"
MUTED = "#303030"
# Accent: teal/green
ACCENT = "#09e39f"

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_MAIN};
}}
QMenuBar {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item:selected {{
    background-color: {BORDER};
    color: {ACCENT};
}}
QMenu {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background-color: {BORDER};
    color: {ACCENT};
}}
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    font-size: 13px;
}}
QDockWidget::title {{
    background-color: {BG_PANEL};
    color: {TEXT};
    padding: 6px 8px;
    border: 1px solid {BORDER};
}}
QScrollArea {{
    background-color: {BG_MAIN};
    border: none;
}}
QPushButton {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 12px;
    border-radius: 4px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:checked {{
    background-color: {BORDER};
    color: {ACCENT};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 8px;
    border-radius: 4px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
}}
QCheckBox {{
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background-color: {BG_PANEL};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
QLabel {{
    color: {TEXT};
}}
QGroupBox {{
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT};
}}
QDialog {{
    background-color: {BG_MAIN};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG_PANEL};
}}
QTabBar::tab {{
    background-color: {BG_PANEL};
    color: {TEXT};
    padding: 8px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
"""
