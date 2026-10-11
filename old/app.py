import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from styles import APP_STYLESHEET
from main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())