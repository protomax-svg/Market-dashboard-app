"""
Application theme: deep-slate surfaces with bright cyan and mint accents.
"""
BG_WINDOW = "#0b1420"
BG_MAIN = "#101b2d"
BG_PANEL = "#142033"
BG_PANEL_ALT = "#1a2a40"
BG_RAISED = "#20314a"
BORDER = "#2f4764"
BORDER_STRONG = "#4f7398"
TEXT = "#eef4fb"
MUTED = "#95aac0"
ACCENT = "#63d2ff"
ACCENT_SOFT = "#1cc8a0"
ACCENT_DIM = "#163b54"
SCROLLBAR = "#355372"

STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {BG_WINDOW};
}}
QWidget {{
    background-color: {BG_MAIN};
    color: {TEXT};
    font-family: "Segoe UI";
    font-size: 10.5pt;
}}
QWidget#CentralCanvas, QWidget#SurfaceRoot {{
    background-color: {BG_MAIN};
}}
QFrame#HeroCard, QFrame#ChartCard, QFrame#DialogCard, QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame#HeroCard {{
    background-color: {BG_PANEL_ALT};
    border: 1px solid {BORDER_STRONG};
}}
QLabel {{
    background-color: transparent;
    color: {TEXT};
}}
QLabel#HeroEyebrow {{
    color: {ACCENT};
    font-size: 9pt;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#HeroTitle {{
    color: {TEXT};
    font-family: "Bahnschrift";
    font-size: 22pt;
    font-weight: 700;
}}
QLabel#HeroSubtitle, QLabel#ChartMeta, QLabel#DialogHint, QLabel#SectionHint {{
    color: {MUTED};
}}
QLabel#HeroPill {{
    background-color: {ACCENT_DIM};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 999px;
    padding: 6px 10px;
    font-size: 9pt;
    font-weight: 600;
}}
QLabel#SectionTitle {{
    color: {TEXT};
    font-family: "Bahnschrift";
    font-size: 13pt;
    font-weight: 700;
}}
QLabel#ChartTitle {{
    color: {TEXT};
    font-family: "Bahnschrift";
    font-size: 12pt;
    font-weight: 700;
}}
QLabel#ChartStatus {{
    background-color: {BG_PANEL_ALT};
    color: {MUTED};
    border: 1px dashed {BORDER};
    border-radius: 10px;
    padding: 8px 10px;
}}
QMenuBar {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
    padding: 4px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 10px;
    border-radius: 8px;
}}
QMenuBar::item:selected {{
    background-color: {BG_PANEL_ALT};
    color: {ACCENT};
}}
QMenu {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 14px;
    border-radius: 8px;
}}
QMenu::item:selected {{
    background-color: {BG_PANEL_ALT};
    color: {ACCENT};
}}
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 10px;
    margin: 2px 16px 2px 16px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {SCROLLBAR};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QPushButton {{
    background-color: {BG_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 7px 14px;
    border-radius: 10px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {BORDER};
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
}}
QPushButton:checked {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {BG_PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 10px;
    border-radius: 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    selection-color: {TEXT};
}}
QCheckBox {{
    color: {TEXT};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background-color: {BG_PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT_SOFT};
    border-color: {ACCENT_SOFT};
}}
QGroupBox {{
    margin-top: 16px;
    padding: 18px 12px 12px 12px;
    color: {TEXT};
    font-family: "Bahnschrift";
    font-size: 12pt;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
}}
QStatusBar {{
    background-color: {BG_PANEL_ALT};
    color: {MUTED};
    border-top: 1px solid {BORDER};
}}
QStatusBar::item {{
    border: none;
}}
QToolTip {{
    background-color: {BG_PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 6px;
}}
"""
