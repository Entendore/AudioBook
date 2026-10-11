"""Minimalist ultra-flat grayscale dark theme stylesheet."""

APP_STYLESHEET = """
/* ── Global ──────────────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #121212;
    color: #dcdcdc;
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}

/* ── Group Boxes ─────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #2a2a2a;
    border-radius: 2px;
    margin-top: 12px;
    padding: 14px 8px 8px 8px;
    font-weight: bold;
    font-size: 13px;
    color: #dcdcdc;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

/* ── Inputs & Dropdowns ──────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 2px;
    padding: 6px;
    color: #dcdcdc;
    selection-background-color: #3a3a3a;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #4a4a4a;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    selection-background-color: #3a3a3a;
    selection-color: #ffffff;
}

/* ── Buttons ─────────────────────────────────────────────────── */
QPushButton {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 2px;
    padding: 6px 14px;
    color: #dcdcdc;
    font-weight: normal;
}
QPushButton:hover {
    background-color: #2a2a2a;
    border-color: #3a3a3a;
}
QPushButton:pressed {
    background-color: #121212;
}
QPushButton:disabled {
    background-color: #121212;
    color: #4a4a4a;
    border-color: #1e1e1e;
}

/* Primary Action */
QPushButton#startBtn {
    background-color: #ffffff;
    color: #121212;
    font-size: 13px;
    font-weight: bold;
    padding: 8px;
    border: none;
    border-radius: 2px;
}
QPushButton#startBtn:hover {
    background-color: #e0e0e0;
}
QPushButton#startBtn:disabled {
    background-color: #2a2a2a;
    color: #4a4a4a;
}

/* Destructive Action */
QPushButton#cancelBtn {
    background-color: transparent;
    color: #dcdcdc;
    font-size: 13px;
    font-weight: normal;
    padding: 8px;
    border: 1px solid #2a2a2a;
    border-radius: 2px;
}
QPushButton#cancelBtn:hover {
    background-color: #1e1e1e;
    border-color: #3a3a3a;
}

/* Secondary Action */
QPushButton#previewBtn {
    background-color: transparent;
    color: #dcdcdc;
    font-weight: normal;
    padding: 8px;
    border: 1px solid #2a2a2a;
    border-radius: 2px;
}
QPushButton#previewBtn:hover {
    background-color: #1e1e1e;
    border-color: #3a3a3a;
}

/* ── Sliders ─────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    border: none;
    height: 4px;
    background: #2a2a2a;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #dcdcdc;
    border: none;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #ffffff;
}

/* ── Progress Bar ────────────────────────────────────────────── */
QProgressBar {
    border: none;
    border-radius: 2px;
    background-color: #1e1e1e;
    text-align: center;
    color: #4a4a4a;
    font-weight: bold;
    font-size: 11px;
    height: 16px;
}
QProgressBar::chunk {
    border-radius: 2px;
    background-color: #dcdcdc;
}

/* ── Tabs ────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #2a2a2a;
    border-radius: 2px;
    padding: 4px;
}
QTabBar::tab {
    background: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 2px;
    border-top-left-radius: 2px;
    border-top-right-radius: 2px;
    color: #7a7a7a;
}
QTabBar::tab:selected {
    background: #121212;
    color: #dcdcdc;
    font-weight: bold;
    border-bottom: 1px solid #121212;
}

/* ── Spin Boxes ──────────────────────────────────────────────── */
QSpinBox {
    background-color: #1e1e1e;
    border: 1px solid #2a2a2a;
    border-radius: 2px;
    padding: 4px;
    color: #dcdcdc;
}

/* ── Checkboxes ──────────────────────────────────────────────── */
QCheckBox {
    color: #dcdcdc;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 2px;
    border: 1px solid #2a2a2a;
    background-color: #1e1e1e;
}
QCheckBox::indicator:checked {
    background-color: #dcdcdc;
    border-color: #dcdcdc;
}

/* ── Specific Custom Widgets ─────────────────────────────────── */
QTextEdit#logConsole {
    background-color: #0a0a0a;
    border: 1px solid #1e1e1e;
    border-radius: 2px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
    color: #7a7a7a;
}
QLabel#statusLabel {
    color: #dcdcdc;
    font-weight: bold;
    font-size: 12px;
}
QLabel#statsLabel {
    color: #4a4a4a;
    font-size: 11px;
}
"""