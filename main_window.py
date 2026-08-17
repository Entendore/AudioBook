"""Main application window — source input, TTS configuration, and production control."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFileDialog, QProgressBar,
    QMessageBox, QTextEdit, QGroupBox, QSpinBox, QSlider, QCheckBox,
    QFormLayout, QTabWidget, QStackedWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, QUrl, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from config import AppConfig, EngineConfig
from engine import AudiobookEngine
from dialogs import VoiceSearchDialog, LocalModelConfigDialog, MetadataDialog, SpeakerMapDialog
from text_processor import TextProcessor
from tts_backends import TTSBackend


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.setWindowTitle("🎙️ Audiobook Studio Pro")
        self.setMinimumSize(config.window_width, config.window_height)
        self.setAcceptDrops(True)

        self.config = config
        self.engine: AudiobookEngine | None = None
        self._player: QMediaPlayer | None = None
        self._preview_thread: QThread | None = None

        self.default_output = str(Path(__file__).resolve().parent / "output")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # ══════════════════════════════════════════════════════════
        # 1. SOURCE TEXT
        # ══════════════════════════════════════════════════════════
        grp_src = QGroupBox("1. Source Text")
        sl = QVBoxLayout(grp_src)
        self.input_tabs = QTabWidget()

        file_tab = QWidget()
        fl = QHBoxLayout(file_tab)
        self.file_edit = QLineEdit()
        self.file_edit.setText(config.last_file)
        self.file_edit.setPlaceholderText("PDF, TXT, DOCX, EPUB, HTML…  (drag & drop)")
        self.file_edit.textChanged.connect(self._auto_name)
        btn_browse = QPushButton("📂 Browse")
        btn_browse.clicked.connect(self._browse_file)
        fl.addWidget(self.file_edit, 1)
        fl.addWidget(btn_browse)

        text_tab = QWidget()
        tl = QVBoxLayout(text_tab)
        self.raw_text = QTextEdit()
        self.raw_text.setPlaceholderText("Paste your text here…")
        self.raw_text.textChanged.connect(self._auto_name)
        tl.addWidget(self.raw_text)

        self.input_tabs.addTab(file_tab, "📄 From File")
        self.input_tabs.addTab(text_tab, "📝 Paste Text")
        self.input_tabs.currentChanged.connect(self._update_stats)
        sl.addWidget(self.input_tabs)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("statsLabel")
        sl.addWidget(self.stats_label)
        root.addWidget(grp_src)

        # ══════════════════════════════════════════════════════════
        # 2. TTS ENGINE
        # ══════════════════════════════════════════════════════════
        grp_tts = QGroupBox("2. TTS Engine")
        tl2 = QVBoxLayout(grp_tts)

        h_be = QHBoxLayout()
        h_be.addWidget(QLabel("Backend:"))
        self.backend_combo = QComboBox()
        for bid, name in TTSBackend.available().items():
            self.backend_combo.addItem(name, bid)
        idx = self.backend_combo.findData(config.backend)
        if idx >= 0: self.backend_combo.setCurrentIndex(idx)
        self.backend_combo.currentIndexChanged.connect(self._on_backend)
        h_be.addWidget(self.backend_combo, 1)
        
        btn_cfg = QPushButton("⚙ Configure")
        btn_cfg.clicked.connect(self._open_backend_config)
        h_be.addWidget(btn_cfg)
        tl2.addLayout(h_be)

        self.backend_stack = QStackedWidget()

        # Edge page
        edge_page = QWidget()
        ef = QFormLayout(edge_page)
        h_v = QHBoxLayout()
        self.edge_voice = QComboBox()
        self.edge_voice.setEditable(True)
        self.edge_voice.addItems([
            "en-US-AvaNeural", "en-US-AndrewNeural", "en-US-SamuelNeural",
            "en-US-MichelleNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural",
        ])
        self.edge_voice.setCurrentText(config.edge_voice)
        btn_sv = QPushButton("🔍 Search All")
        btn_sv.clicked.connect(self._voice_search)
        h_v.addWidget(self.edge_voice, 1)
        h_v.addWidget(btn_sv)
        ef.addRow("Voice:", h_v)

        self.edge_rate, self.edge_rate_lbl = self._make_slider("Speed:", config.edge_rate, "%")
        ef.addRow(self.edge_rate)
        self.edge_vol, self.edge_vol_lbl = self._make_slider("Volume:", config.edge_volume, "%")
        ef.addRow(self.edge_vol)
        self.edge_pitch, self.edge_pitch_lbl = self._make_slider("Pitch:", config.edge_pitch, "Hz")
        ef.addRow(self.edge_pitch)
        self.backend_stack.addWidget(edge_page)

        # Qwen Local page
        qwen_page = QWidget()
        qf = QFormLayout(qwen_page)
        self.qwen_voice = QComboBox()
        self.qwen_voice.setEditable(True)
        self.qwen_voice.addItems(["Cherry", "Serena", "Ethan", "Chelsie", "Echo", "Bonnie"])
        self.qwen_voice.setCurrentText(config.qwen_voice)
        qf.addRow("Voice:", self.qwen_voice)
        self.qwen_status = QLabel("Model: " + (config.qwen_model_path or "Not Set"))
        qf.addRow(self.qwen_status)
        self.backend_stack.addWidget(qwen_page)

        # OmniVoice Local page
        omni_page = QWidget()
        of_layout = QFormLayout(omni_page)
        self.omni_speaker = QSpinBox()
        self.omni_speaker.setRange(0, 100)
        self.omni_speaker.setValue(config.omnivoice_speaker_id)
        of_layout.addRow("Speaker ID:", self.omni_speaker)
        self.omni_status = QLabel("Model: " + (config.omnivoice_model_path or "Not Set"))
        of_layout.addRow(self.omni_status)
        self.backend_stack.addWidget(omni_page)

        tl2.addWidget(self.backend_stack)
        root.addWidget(grp_tts)
        self._on_backend()

        # ══════════════════════════════════════════════════════════
        # 3. OUTPUT
        # ══════════════════════════════════════════════════════════
        grp_out = QGroupBox("3. Output")
        out_form = QFormLayout(grp_out)
        self.out_name = QLineEdit()
        self.out_name.setPlaceholderText("Auto-filled from source")
        out_form.addRow("Filename:", self.out_name)

        h_dir = QHBoxLayout()
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText(f"Auto: {self.default_output}")
        self.out_dir.setText(config.output_dir)
        self.out_dir.textChanged.connect(self._auto_name)
        btn_dir = QPushButton("📁 Folder")
        btn_dir.clicked.connect(self._browse_dir)
        h_dir.addWidget(self.out_dir, 1)
        h_dir.addWidget(btn_dir)
        out_form.addRow("Directory:", h_dir)

        h_fmt = QHBoxLayout()
        self.chk_mp3 = QCheckBox("MP3")
        self.chk_wav = QCheckBox("WAV")
        self.chk_m4b = QCheckBox("M4B")
        fmt = config.output_format
        self.chk_mp3.setChecked(fmt in ("mp3", "both", "all"))
        self.chk_wav.setChecked(fmt in ("wav", "both", "all"))
        self.chk_m4b.setChecked(fmt in ("m4b", "all"))
        h_fmt.addWidget(self.chk_mp3)
        h_fmt.addWidget(self.chk_wav)
        h_fmt.addWidget(self.chk_m4b)
        h_fmt.addStretch()
        out_form.addRow("Format:", h_fmt)
        root.addWidget(grp_out)

        # ══════════════════════════════════════════════════════════
        # 4. QUALITY & MULTI-SPEAKER
        # ══════════════════════════════════════════════════════════
        grp_q = QGroupBox("4. Quality & Voices")
        ql = QFormLayout(grp_q)

        self.chk_norm = QCheckBox("EBU R128 loudness normalization (−16 LUFS)")
        self.chk_norm.setChecked(config.normalize_audio)
        ql.addRow(self.chk_norm)

        self.chk_trim = QCheckBox("Trim inter-chunk silence")
        self.chk_trim.setChecked(config.trim_silence)
        ql.addRow(self.chk_trim)

        self.chk_chapters = QCheckBox("Chapter-aware generation")
        self.chk_chapters.setChecked(config.chapter_aware)
        ql.addRow(self.chk_chapters)

        h_ms = QHBoxLayout()
        self.chk_multi = QCheckBox("Multi-Speaker (NLP)")
        self.chk_multi.setChecked(config.multi_speaker)
        h_ms.addWidget(self.chk_multi)
        
        self.btn_speakers = QPushButton("🗣 Map Book Characters")
        self.btn_speakers.clicked.connect(self._open_speaker_map)
        self.btn_speakers.setEnabled(config.multi_speaker)
        self.chk_multi.toggled.connect(self.btn_speakers.setEnabled)
        h_ms.addWidget(self.btn_speakers)
        ql.addRow(h_ms)
        root.addWidget(grp_q)

        # ══════════════════════════════════════════════════════════
        # 5. PERFORMANCE
        # ══════════════════════════════════════════════════════════
        grp_p = QGroupBox("5. Performance")
        pf = QFormLayout(grp_p)
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 50)
        self.spin_workers.setValue(config.concurrency)
        pf.addRow("Parallel Workers:", self.spin_workers)

        self.spin_chunk = QSpinBox()
        self.spin_chunk.setRange(100, 3000)
        self.spin_chunk.setSingleStep(50)
        self.spin_chunk.setValue(config.chunk_size)
        pf.addRow("Chunk Size (chars):", self.spin_chunk)
        root.addWidget(grp_p)

        # ══════════════════════════════════════════════════════════
        # 6. ACTIONS
        # ══════════════════════════════════════════════════════════
        h_act = QHBoxLayout()
        self.btn_preview = QPushButton("🔊 Preview")
        self.btn_preview.setObjectName("previewBtn")
        self.btn_preview.clicked.connect(self._preview)
        h_act.addWidget(self.btn_preview)

        self.btn_meta = QPushButton("🏷 Metadata")
        self.btn_meta.clicked.connect(self._open_metadata)
        h_act.addWidget(self.btn_meta)

        self.btn_start = QPushButton("🚀 Produce Audiobook")
        self.btn_start.setObjectName("startBtn")
        self.btn_start.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_start.clicked.connect(self._start)
        h_act.addWidget(self.btn_start, 1)

        self.btn_cancel = QPushButton("✖ Cancel")
        self.btn_cancel.setObjectName("cancelBtn")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        h_act.addWidget(self.btn_cancel)
        root.addLayout(h_act)

        # ══════════════════════════════════════════════════════════
        # 7. STATUS
        # ══════════════════════════════════════════════════════════
        self.pbar = QProgressBar()
        root.addWidget(self.pbar)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("statusLabel")
        root.addWidget(self.status_lbl)

        self.log_box = QTextEdit()
        self.log_box.setObjectName("logConsole")
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(160)
        root.addWidget(self.log_box)

        self._auto_name()
        self._update_stats()

    # ═════════════════════════════════════════════════════════════
    # WIDGET HELPERS
    # ═════════════════════════════════════════════════════════════

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path: self.file_edit.setText(path); self.input_tabs.setCurrentIndex(0); break

    def _make_slider(self, label: str, raw: str, unit: str):
        h = QHBoxLayout()
        h.addWidget(QLabel(label))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(-50, 50)
        try: v = int(str(raw).replace("%", "").replace("Hz", "").replace("+", ""))
        except: v = 0
        sl.setValue(v)
        lbl = QLabel(f"{v:+d}{unit}")
        sl.valueChanged.connect(lambda val, u=unit, l=lbl: l.setText(f"{val:+d}{u}"))
        h.addWidget(sl, 1)
        h.addWidget(lbl)
        return h, lbl

    def _out_dir(self) -> str:
        d = self.out_dir.text().strip()
        return d or self.default_output

    def _unique_name(self, directory: str, base: str) -> str:
        safe = re.sub(r'[\\/*?:"<>|]', "", base)[:50]
        name, c = safe, 1
        while Path(directory, f"{name}.mp3").exists(): name = f"{safe}_{c}"; c += 1
        return name

    def _auto_name(self):
        is_raw = self.input_tabs.currentIndex() == 1
        d = self._out_dir()
        if not is_raw:
            fp = self.file_edit.text().strip()
            base = Path(fp).stem if fp else "Untitled"
        else:
            raw = self.raw_text.toPlainText().strip()
            first = raw.split("\n")[0] if raw else "New_Text"
            base = re.sub(r'[\\/*?:"<>|]', "", first)[:40]
        self.out_name.setText(self._unique_name(d, base))

    def _update_stats(self):
        is_raw = self.input_tabs.currentIndex() == 1
        source = self.raw_text.toPlainText() if is_raw else self.file_edit.text()
        if not source or (not is_raw and not Path(source).exists()):
            self.stats_label.setText(""); return
        try:
            stats = TextProcessor.compute_stats(source, is_raw)
            self.stats_label.setText(
                f"📝 {stats.word_count:,} words  •  ⏱ ~{stats.estimated_str}  •  "
                f"📖 {stats.chapter_count} chapter(s)  •  🗣 {stats.speakers_detected} character(s)"
            )
        except: self.stats_label.setText("")

    def _fmt_string(self) -> str:
        mp3, wav, m4b = self.chk_mp3.isChecked(), self.chk_wav.isChecked(), self.chk_m4b.isChecked()
        if m4b and mp3 and wav: return "all"
        if m4b and mp3: return "all"
        if m4b: return "m4b"
        if mp3 and wav: return "both"
        if wav: return "wav"
        return "mp3"

    # ═════════════════════════════════════════════════════════════
    # BUILD CONFIGS
    # ═════════════════════════════════════════════════════════════

    def _build_engine_config(self) -> EngineConfig:
        bid = self.backend_combo.currentData()
        if bid == "qwen_local":
            voice = self.qwen_voice.currentText()
            rate, volume, pitch = "+0%", "+0%", "+0Hz"
        elif bid == "omnivoice_local":
            voice = str(self.omni_speaker.value())
            rate, volume, pitch = "+0%", "+0%", "+0Hz"
        else:
            voice = self.edge_voice.currentText()
            rate = self.edge_rate_lbl.text()
            volume = self.edge_vol_lbl.text()
            pitch = self.edge_pitch_lbl.text()

        return EngineConfig(
            backend_id=bid, voice=voice, rate=rate, volume=volume, pitch=pitch,
            concurrency=self.spin_workers.value(), chunk_size=self.spin_chunk.value(),
            output_format=self._fmt_string(), normalize=self.chk_norm.isChecked(),
            trim_silence=self.chk_trim.isChecked(), chapter_aware=self.chk_chapters.isChecked(),
            multi_speaker=self.chk_multi.isChecked(), voice_map=self.config.voice_map,
            title=self.config.book_title or self.out_name.text() or "Audiobook",
            author=self.config.book_author or "Unknown", cover_art=self.config.cover_art,
            qwen_model_path=self.config.qwen_model_path, qwen_device=self.config.qwen_device,
            omnivoice_model_path=self.config.omnivoice_model_path, omnivoice_device=self.config.omnivoice_device,
            omnivoice_speaker_id=self.config.omnivoice_speaker_id,
        )

    def _backend_config_dict(self) -> dict: return self.config.to_dict()

    # ═════════════════════════════════════════════════════════════
    # SLOTS
    # ═════════════════════════════════════════════════════════════

    def _on_backend(self):
        bid = self.backend_combo.currentData()
        if bid == "qwen_local": self.backend_stack.setCurrentIndex(1)
        elif bid == "omnivoice_local": self.backend_stack.setCurrentIndex(2)
        else: self.backend_stack.setCurrentIndex(0)

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open Document", "", "Documents (*.txt *.pdf *.docx *.md *.html *.htm *.epub)")
        if f: self.file_edit.setText(f); self._update_stats()

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if d: self.out_dir.setText(d)

    def _voice_search(self):
        bid = self.backend_combo.currentData()
        backend = TTSBackend.create(bid, self._backend_config_dict())
        dlg = VoiceSearchDialog(backend, self.edge_voice.currentText(), self)
        if dlg.exec():
            v = dlg.get_selected()
            if v: self.edge_voice.setCurrentText(v)

    def _open_backend_config(self):
        bid = self.backend_combo.currentData()
        if bid in ("qwen_local", "omnivoice_local"):
            dlg = LocalModelConfigDialog(self.config.to_dict(), bid, self)
            if dlg.exec():
                self.config = AppConfig.from_dict(dlg.get_config())
                self._on_backend() # Refresh status labels
        else:
            QMessageBox.information(self, "Edge TTS", "Edge TTS uses Microsoft's free cloud voices. No local config needed.")

    def _open_metadata(self):
        dlg = MetadataDialog(self.config.to_dict(), self)
        if dlg.exec(): self.config = AppConfig.from_dict(dlg.get_config())

    def _open_speaker_map(self):
        is_raw = self.input_tabs.currentIndex() == 1
        source = self.raw_text.toPlainText() if is_raw else self.file_edit.text()
        detected = []
        if source and (is_raw or Path(source).exists()):
            try: detected = TextProcessor.extract_speakers(source, is_raw)
            except: pass
        bid = self.backend_combo.currentData()
        backend = TTSBackend.create(bid, self._backend_config_dict())
        dlg = SpeakerMapDialog(self.config.to_dict(), detected, backend, self)
        if dlg.exec(): self.config = AppConfig.from_dict(dlg.get_config())

    def _preview(self):
        is_raw = self.input_tabs.currentIndex() == 1
        if is_raw: text = self.raw_text.toPlainText().strip()
        else:
            fp = self.file_edit.text().strip()
            if fp and Path(fp).exists():
                chunks = list(TextProcessor.chunk_generator(fp, 300, False))
                text = chunks[0].text if chunks else ""
            else: text = ""
        if not text: QMessageBox.warning(self, "Preview", "No text available."); return

        text = text[:300]
        ecfg = self._build_engine_config()
        backend = TTSBackend.create(ecfg.backend_id, self._backend_config_dict())
        self.btn_preview.setEnabled(False)
        self.log_box.append("<i>Generating preview…</i>")
        preview_file = str(Path(tempfile.gettempdir()) / "audiobook_preview.mp3")

        class _PT(QThread):
            done = Signal(bool, str)
            def __init__(self, be, txt, path, voice):
                super().__init__(); self.be, self.txt, self.path, self.voice = be, txt, path, voice
            def run(self):
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self.be.preview(self.txt, self.path, self.voice))
                    self.done.emit(True, self.path)
                except Exception as e: self.done.emit(False, str(e))
                finally:
                    try: loop.run_until_complete(self.be.close())
                    except: pass
                    loop.close()

        self._preview_thread = _PT(backend, text, preview_file, ecfg.voice)
        self._preview_thread.done.connect(self._on_preview_done)
        self._preview_thread.start()

    def _on_preview_done(self, ok, result):
        self.btn_preview.setEnabled(True)
        if ok: self.log_box.append('<font color="#a6e3a1">✓ Preview ready</font>'); self._play(result)
        else: self.log_box.append(f'<font color="red">Preview failed: {result}</font>')

    def _play(self, path: str):
        if not Path(path).exists(): return
        if self._player: self._player.stop()
        out = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(out)
        self._player.setSource(QUrl.fromLocalFile(path))
        out.setVolume(0.8); self._player.play()

    def _start(self):
        is_raw = self.input_tabs.currentIndex() == 1
        source = self.raw_text.toPlainText().strip() if is_raw else self.file_edit.text().strip()
        if is_raw and not source: QMessageBox.warning(self, "Error", "Please enter text."); return
        if not is_raw and (not source or not Path(source).exists()): QMessageBox.warning(self, "Error", "Please select a valid file."); return

        ecfg = self._build_engine_config()
        backend = TTSBackend.create(ecfg.backend_id, self._backend_config_dict())
        errors = backend.validate_config()
        try:
            loop = asyncio.new_event_loop(); loop.run_until_complete(backend.close()); loop.close()
        except: pass

        if errors: QMessageBox.critical(self, "Configuration Error", "Please fix:\n\n• " + "\n• ".join(errors)); return

        out_dir = self._out_dir()
        try: os.makedirs(out_dir, exist_ok=True)
        except OSError as e: QMessageBox.critical(self, "Error", f"Cannot create output dir:\n{e}"); return

        full_out = str(Path(out_dir) / (self.out_name.text() or "Audiobook"))
        self._save_state(); self.log_box.clear(); self.pbar.setValue(0)
        self.status_lbl.setText("Starting…")
        self.btn_start.setEnabled(False); self.btn_preview.setEnabled(False); self.btn_cancel.setEnabled(True)

        backend = TTSBackend.create(ecfg.backend_id, self._backend_config_dict())
        self.engine = AudiobookEngine(source=source, output_path=full_out, config=ecfg, backend=backend, is_raw_text=is_raw)
        self.engine.progress.connect(self._on_progress)
        self.engine.log.connect(lambda s: self.log_box.append(s))
        self.engine.chapter_progress.connect(self._on_chapter)
        self.engine.finished.connect(self._on_finished)
        self.engine.start()

    def _cancel(self):
        if self.engine: self.engine.cancel()

    def _on_progress(self, pct, txt): self.pbar.setValue(pct); self.status_lbl.setText(txt)

    def _on_chapter(self, cur, total): self.log_box.append(f'<b>📖 Processing chapter {cur}/{total}</b>')

    def _on_finished(self, success, msg):
        self.btn_start.setEnabled(True); self.btn_preview.setEnabled(True); self.btn_cancel.setEnabled(False); self.engine = None
        if success:
            self.pbar.setValue(100); self.status_lbl.setText("✓ Complete!"); self.log_box.append(msg)
            QMessageBox.information(self, "Audiobook Complete", msg)
            if self.input_tabs.currentIndex() == 1: self._auto_name()
        else:
            self.status_lbl.setText("✗ Failed"); self.log_box.append(f'<font color="red"><b>Error:</b> {msg}</font>')
            QMessageBox.critical(self, "Production Error", msg)

    def _save_state(self):
        c = self.config
        c.backend = self.backend_combo.currentData()
        c.edge_voice = self.edge_voice.currentText(); c.edge_rate = self.edge_rate_lbl.text()
        c.edge_volume = self.edge_vol_lbl.text(); c.edge_pitch = self.edge_pitch_lbl.text()
        c.qwen_voice = self.qwen_voice.currentText()
        c.omnivoice_speaker_id = self.omni_speaker.value()
        c.concurrency = self.spin_workers.value()
        c.chunk_size = self.spin_chunk.value(); c.output_format = self._fmt_string()
        c.output_dir = self.out_dir.text(); c.last_file = self.file_edit.text()
        c.normalize_audio = self.chk_norm.isChecked(); c.trim_silence = self.chk_trim.isChecked()
        c.chapter_aware = self.chk_chapters.isChecked()
        c.multi_speaker = self.chk_multi.isChecked()

    def save_state(self):
        self._save_state()
        self.config.window_width = self.width(); self.config.window_height = self.height()
        self.config.save()