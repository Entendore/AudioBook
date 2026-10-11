"""Audiobook Studio Pro — Application entry point."""

import logging
import sys

from PySide6.QtWidgets import QApplication

from config import AppConfig
from styles import APP_STYLESHEET
from main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("audiobook")


def main():
    config = AppConfig.load()

    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    app.setStyle("Fusion")

    window = MainWindow(config)
    window.show()

    ret = app.exec()

    window.save_state()
    config.save()
    return ret


if __name__ == "__main__":
    sys.exit(main())