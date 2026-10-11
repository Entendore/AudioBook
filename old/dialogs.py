import asyncio

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QDialogButtonBox,
    QGroupBox, QFormLayout, QMessageBox, QComboBox,
)
from PySide6.QtCore import Qt, QThread, Signal

from tts_backends.base import VoiceInfo


# ── Async voice loader thread ──────────────────────────────────

class VoiceLoadWorker(QThread):
    finished = Signal(list)  # List[VoiceInfo]

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend

    def run(self):
        loop = asyncio.new_event_loop()
        try:
            voices = loop.run_until_complete(self.backend.list_voices())
            self.finished.emit(voices)
        except Exception:
            self.finished.emit([])
        finally:
            loop.close()


# ── Voice Search Dialog ────────────────────────────────────────

class VoiceSearchDialog(QDialog):
    def __init__(self, backend, current_voice: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Voices")
        self.resize(520, 600)
        self.selected_voice_id: str = current_voice

        layout = QVBoxLayout(self)

        # Search bar
        h_search = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍  Filter voices by name, locale, gender…")
        self.search_edit.textChanged.connect(self._filter)
        h_search.addWidget(self.search_edit)
        layout.addLayout(h_search)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setSortingEnabled(True)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        # Status
        self.status_label = QLabel("Loading voices…")
        layout.addWidget(self.status_label)

        # Buttons
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self._all_voices: list = []
        self._load(backend)

    def _load(self, backend):
        self.worker = VoiceLoadWorker(backend)
        self.worker.finished.connect(self._on_loaded)
        self.worker.start()

    def _on_loaded(self, voices: list):
        self._all_voices = voices
        self.status_label.setText(f"{len(voices)} voices available")
        self._populate(voices)

    def _populate(self, voices: list):
        self.list_widget.clear()
        for v in voices:
            item = QListWidgetItem(v.display())
            item.setData(Qt.UserRole, v.id)
            self.list_widget.addItem(item)

    def _filter(self, text: str):
        text = text.lower()
        filtered = [
            v for v in self._all_voices
            if text in v.display().lower()
        ]
        self._populate(filtered)

    def get_selected_voice(self) -> str:
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.UserRole)
        return self.selected_voice_id


# ── Qwen API Configuration Dialog ─────────────────────────────

class QwenConfigDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Qwen3 OmniVoice — API Configuration")
        self.setMinimumWidth(480)
        self.config = config.copy()

        layout = QVBoxLayout(self)

        grp = QGroupBox("DashScope / OpenAI-Compatible API")
        form = QFormLayout(grp)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-… or your DashScope API key")
        self.key_edit.setText(config.get("qwen_api_key", ""))
        form.addRow("API Key:", self.key_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setText(config.get("qwen_model", "cosyvoice-v2"))
        form.addRow("Model:", self.model_edit)

        self.url_edit = QLineEdit()
        self.url_edit.setText(
            config.get(
                "qwen_base_url",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        )
        self.url_edit.setPlaceholderText("https://dashscope.aliyuncs.com/compatible-mode/v1")
        form.addRow("Base URL:", self.url_edit)

        layout.addWidget(grp)

        info = QLabel(
            "ℹ️  Get your API key from "
            '<a href="https://dashscope.console.aliyun.com/">DashScope Console</a>'
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _save(self):
        self.config["qwen_api_key"] = self.key_edit.text().strip()
        self.config["qwen_model"] = self.model_edit.text().strip()
        self.config["qwen_base_url"] = self.url_edit.text().strip()
        self.accept()

    def get_config(self) -> dict:
        return self.config