APP_STYLESHEET = """
QMainWindow {
    background-color: #1e1e2e;
}
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: bold;
    font-size: 14px;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
}
QLineEdit, QTextEdit, QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #89b4fa;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    border: 1px solid #45475a;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QPushButton {
    background-color: #45475a;
    border: 1px solid #585b70;
    border-radius: 6px;
    padding: 8px 16px;
    color: #cdd6f4;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #585b70;
    border-color: #89b4fa;
}
QPushButton:pressed {
    background-color: #313244;
}
QPushButton:disabled {
    background-color: #313244;
    color: #585b70;
    border-color: #313244;
}
QPushButton#startBtn {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-size: 15px;
    font-weight: bold;
    padding: 12px;
    border: none;
    border-radius: 8px;
}
QPushButton#startBtn:hover {
    background-color: #94e2d5;
}
QPushButton#startBtn:disabled {
    background-color: #45475a;
    color: #585b70;
}
QPushButton#cancelBtn {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-size: 15px;
    font-weight: bold;
    padding: 12px;
    border: none;
    border-radius: 8px;
}
QPushButton#cancelBtn:hover {
    background-color: #eba0ac;
}
QPushButton#previewBtn {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    padding: 12px;
    border: none;
    border-radius: 8px;
}
QPushButton#previewBtn:hover {
    background-color: #b4befe;
}
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #45475a;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #89b4fa;
    border: none;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #b4befe;
}
QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #313244;
    text-align: center;
    color: #cdd6f4;
    font-weight: bold;
    height: 22px;
}
QProgressBar::chunk {
    border-radius: 6px;
    background-color: #89b4fa;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px;
}
QTabBar::tab {
    background: #313244;
    border: 1px solid #45475a;
    padding: 8px 20px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #a6adc8;
}
QTabBar::tab:selected {
    background: #45475a;
    color: #89b4fa;
    font-weight: bold;
}
QSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px;
    color: #cdd6f4;
}
QCheckBox {
    color: #cdd6f4;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #45475a;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}
QTextEdit#logConsole {
    background-color: #11111b;
    border: 1px solid #313244;
    border-radius: 6px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    color: #a6adc8;
}
QLabel#statusLabel {
    color: #89b4fa;
    font-weight: bold;
    font-size: 13px;
}
"""