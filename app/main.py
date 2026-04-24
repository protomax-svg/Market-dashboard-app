"""
MarketMetrics desktop app entry point.
"""
import logging
import os
import sys

# Reduce QtWebEngine/Chromium GPU errors on Windows.
if "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ:
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing"

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import STYLESHEET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    logger.info("Starting MarketMetrics")
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setApplicationName("MarketMetrics")
    app.setOrganizationName("MarketMetrics")
    app.setQuitOnLastWindowClosed(True)
    try:
        win = MainWindow()
        win.show()
        win.raise_()
        win.activateWindow()
        return app.exec()
    except Exception:
        logger.exception("Launch failed")
        raise


if __name__ == "__main__":
    sys.exit(main())
