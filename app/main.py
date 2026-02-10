"""
MarketMetrics desktop app entry point.
"""
import logging
import os
import sys

# Reduce QtWebEngine/Chromium GPU errors (e.g. IDCompositionDevice4 / DirectComposition on Windows)
# Set before importing PySide6 so WebEngine picks it up.
if "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setApplicationName("MarketMetrics")
    app.setOrganizationName("MarketMetrics")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
