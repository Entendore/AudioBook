"""Voice search, local model configuration, metadata, and speaker mapping dialogs."""

import asyncio

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QDialogButtonBox,
    QGroupBox, QFormLayout, QMessageBox, QFileDialog, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QSpinBox
)
from PySide6.QtCore import Qt, QThread, Signal

from tts_backends import TTSBackend, VoiceInfo


class VoiceLoadWorker(QThread):
    finished = Signal(list)
    def __init__(self, backend: TTSBackend, parent=None):
        super().__init__(parent)
        self._backend = backend

    def run(self):
        loop = asyncio.new_event_loop()
        try:
            voices = loop.run_until_complete(self._backend.list_voices())
            self.finished.emit(voices)
        except Exception: self.finished.emit([])
        finally:
            try: loop.run_until_complete(self._backend.close())
            except Exception: pass
            loop.close()


class VoiceSearchDialog(QDialog):
    def __init__(self, backend: TTSBackend, current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Voices")
        self.resize(520, 600)
        self.selected_id = current

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Filter by name, locale, gender…")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setSortingEnabled(True)
        self.list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list)

        self.status = QLabel("Loading voices…")
        layout.addWidget(self.status)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

        self._all: list = []
        self._worker = VoiceLoadWorker(backend)
        self._worker.finished.connect(self._on_loaded)
        self._worker.start()

    def _on_loaded(self, voices: list):
        self._all = voices
        self.status.setText(f"{len(voices)} voices available")
        self._populate(voices)

    def _populate(self, voices: list):
        self.list.clear()
        for v in voices:
            item = QListWidgetItem(v.display())
            item.setData(Qt.UserRole, v.id)
            self.list.addItem(item)

    def _filter(self, text: str):
        t = text.lower()
        self._populate([v for v in self._all if t in v.display().lower()])

    def get_selected(self) -> str:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else self.selected_id


# ── Local Model Configuration Dialog ────────────────────────────

class LocalModelConfigDialog(QDialog):
    """Configuration for local PyTorch/Transformers models."""
    def __init__(self, config: dict, backend_id: str, parent=None):
        super().__init__(parent)
        self.cfg = config.copy()
        self.backend_id = backend_id
        
        if backend_id == "qwen_local":
            self.setWindowTitle("Qwen Local TTS — Configuration")
            model_key, device_key = "qwen_model_path", "qwen_device"
        else:
            self.setWindowTitle("OmniVoice Local TTS — Configuration")
            model_key, device_key = "omnivoice_model_path", "omnivoice_device"

        layout = QVBoxLayout(self)
        grp = QGroupBox("Local Model Settings")
        form = QFormLayout(grp)

        h_path = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setText(self.cfg.get(model_key, ""))
        self.path_edit.setPlaceholderText("HuggingFace Repo ID or local /path/to/model")
        h_path.addWidget(self.path_edit, 1)
        btn_browse = QPushButton("📁")
        btn_browse.clicked.connect(lambda: self._browse_model(model_key))
        h_path.addWidget(btn_browse)
        form.addRow("Model Path:", h_path)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["cuda", "cpu"])
        self.device_combo.setCurrentText(self.cfg.get(device_key, "cuda"))
        form.addRow("Device:", self.device_combo)

        layout.addWidget(grp)

        info = QLabel("ℹ️ Requires PyTorch and Transformers installed locally.")
        info.setWordWrap(True)
        layout.addWidget(info)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self._save)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _browse_model(self, key: str):
        d = QFileDialog.getExistingDirectory(self, "Select Local Model Directory")
        if d: self.path_edit.setText(d)

    def _save(self):
        if self.backend_id == "qwen_local":
            self.cfg["qwen_model_path"] = self.path_edit.text().strip()
            self.cfg["qwen_device"] = self.device_combo.currentText()
        else:
            self.cfg["omnivoice_model_path"] = self.path_edit.text().strip()
            self.cfg["omnivoice_device"] = self.device_combo.currentText()
        self.accept()

    def get_config(self) -> dict: return self.cfg


class MetadataDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audiobook Metadata")
        self.cfg = config.copy()

        layout = QVBoxLayout(self)
        grp = QGroupBox("Book Information")
        form = QFormLayout(grp)

        self.title_edit = QLineEdit()
        self.title_edit.setText(config.get("book_title", ""))
        form.addRow("Title:", self.title_edit)

        self.author_edit = QLineEdit()
        self.author_edit.setText(config.get("book_author", ""))
        form.addRow("Author:", self.author_edit)

        h_cover = QHBoxLayout()
        self.cover_edit = QLineEdit()
        self.cover_edit.setText(config.get("cover_art", ""))
        btn_browse = QPushButton("🖼 Browse")
        btn_browse.clicked.connect(self._browse_cover)
        h_cover.addWidget(self.cover_edit, 1)
        h_cover.addWidget(btn_browse)
        form.addRow("Cover Art:", h_cover)
        layout.addWidget(grp)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self._save)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def _browse_cover(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Cover Art", "", "Images (*.jpg *.jpeg *.png)")
        if f: self.cover_edit.setText(f)

    def _save(self):
        self.cfg["book_title"] = self.title_edit.text().strip()
        self.cfg["book_author"] = self.author_edit.text().strip()
        self.cfg["cover_art"] = self.cover_edit.text().strip()
        self.accept()

    def get_config(self) -> dict: return self.cfg


class SpeakerMapDialog(QDialog):
    """Map NLP-detected speakers to specific TTS voices."""
    def __init__(self, config: dict, detected_speakers: list, backend: TTSBackend, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Multi-Speaker Voice Mapping (NLP)")
        self.setMinimumWidth(550)
        self.cfg = config.copy()
        self._backend = backend
        self._voices: list = []

        layout = QVBoxLayout(self)
        info = QLabel("Assign a voice to each character. Unmapped characters use Narrator.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Speaker / Character", "Voice ID"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.accepted.connect(self._save)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

        voice_map = self.cfg.get("voice_map", {})
        speakers_set = {"Narrator", "Dialogue"}
        speakers_set.update(detected_speakers)
        speakers_set.update(voice_map.keys())
        speakers = sorted(list(speakers_set), key=lambda x: (0 if x == "Narrator" else 1 if x == "Dialogue" else 2, x))
        
        self.table.setRowCount(len(speakers))
        for row, speaker in enumerate(speakers):
            item = QTableWidgetItem(speaker)
            self.table.setItem(row, 0, item)
            combo = QComboBox()
            combo.setEditable(True)
            current_voice = voice_map.get(speaker, "")
            if current_voice: combo.setCurrentText(current_voice)
            self.table.setCellWidget(row, 1, combo)

        self._worker = VoiceLoadWorker(backend)
        self._worker.finished.connect(self._on_voices_loaded)
        self._worker.start()

    def _on_voices_loaded(self, voices: list):
        self._voices = voices
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 1)
            if combo:
                for v in voices: combo.addItem(v.id)
                current = self.cfg.get("voice_map", {}).get(self.table.item(row, 0).text(), "")
                if current: combo.setCurrentText(current)

    def _save(self):
        voice_map = {}
        for row in range(self.table.rowCount()):
            speaker_item = self.table.item(row, 0)
            combo = self.table.cellWidget(row, 1)
            if not speaker_item: continue
            speaker = speaker_item.text().strip()
            voice = combo.currentText().strip() if combo else ""
            if speaker and voice: voice_map[speaker] = voice
        self.cfg["voice_map"] = voice_map
        self.accept()

    def get_config(self) -> dict: return self.cfg