import os
import re
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QFileDialog, QProgressBar,
    QMessageBox, QTextEdit, QGroupBox, QSpinBox, QSlider, QCheckBox,
    QFormLayout, QTabWidget, QStackedWidget, QSizePolicy, QRadioButton,
    QButtonGroup,
)
from PySide6.QtCore import Qt, QUrl, QThread, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from config import load_config, save_config
from audio_engine import AudioEngine
from chapter_engine import ChapterEngine
from dialogs import VoiceSearchDialog, QwenConfigDialog
from tts_backends import create_backend, get_available_backends
from tts_backends.base import TTSBackend


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎙️ Audiobook Studio Pro")
        self.setMinimumSize(850, 950)

        self.config = load_config()
        self.engine = None
        self._media_player = None

        self.default_output_dir = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "output"
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # ══════════════════════════════════════════════════════════
        # 1. SOURCE TEXT
        # ══════════════════════════════════════════════════════════
        grp_src = QGroupBox("1. Source Text")
        src_layout = QVBoxLayout(grp_src)

        self.input_tabs = QTabWidget()

        # — File tab —
        file_tab = QWidget()
        file_layout = QHBoxLayout(file_tab)
        self.file_edit = QLineEdit()
        self.file_edit.setText(self.config.get("last_file", ""))
        self.file_edit.setPlaceholderText("PDF, TXT, DOCX, EPUB, HTML…")
        self.file_edit.textChanged.connect(self._auto_name)
        btn_browse = QPushButton("📂 Browse")
        btn_browse.clicked.connect(self._browse_file)
        file_layout.addWidget(self.file_edit, 1)
        file_layout.addWidget(btn_browse)

        # — Text tab —
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        self.raw_text = QTextEdit()
        self.raw_text.setPlaceholderText("Paste your text here…")
        self.raw_text.textChanged.connect(self._auto_name)
        text_layout.addWidget(self.raw_text)

        self.input_tabs.addTab(file_tab, "📄 From File")
        self.input_tabs.addTab(text_tab, "📝 Paste Text")
        src_layout.addWidget(self.input_tabs)
        root.addWidget(grp_src)

        # ══════════════════════════════════════════════════════════
        # 2. TTS ENGINE
        # ══════════════════════════════════════════════════════════
        grp_tts = QGroupBox("2. TTS Engine")
        tts_layout = QVBoxLayout(grp_tts)

        # Backend selector row
        h_be = QHBoxLayout()
        h_be.addWidget(QLabel("Backend:"))
        self.backend_combo = QComboBox()
        for bid, name in get_available_backends().items():
            self.backend_combo.addItem(name, bid)
        saved_be = self.config.get("backend", "edge_tts")
        idx = self.backend_combo.findData(saved_be)
        if idx >= 0:
            self.backend_combo.setCurrentIndex(idx)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        h_be.addWidget(self.backend_combo, 1)
        btn_be_cfg = QPushButton("⚙ Configure")
        btn_be_cfg.clicked.connect(self._open_backend_config)
        h_be.addWidget(btn_be_cfg)
        tts_layout.addLayout(h_be)

        # Stacked pages for backend-specific controls
        self.backend_stack = QStackedWidget()

        # ── Edge TTS page ──
        edge_page = QWidget()
        ef = QFormLayout(edge_page)

        h_voice = QHBoxLayout()
        self.edge_voice_combo = QComboBox()
        self.edge_voice_combo.setEditable(True)
        self.edge_voice_combo.addItems([
            "en-US-AvaNeural", "en-US-AndrewNeural",
            "en-US-SamuelNeural", "en-US-MichelleNeural",
            "en-GB-SoniaNeural", "en-GB-RyanNeural",
            "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural",
            "ja-JP-NanamiNeural", "de-DE-KatjaNeural",
            "fr-FR-DeniseNeural", "es-ES-ElviraNeural",
        ])
        self.edge_voice_combo.setCurrentText(self.config.get("edge_voice", ""))
        btn_voice = QPushButton("🔍 Search All")
        btn_voice.clicked.connect(self._open_voice_search)
        h_voice.addWidget(self.edge_voice_combo, 1)
        h_voice.addWidget(btn_voice)
        ef.addRow("Voice:", h_voice)

        # Sliders — store actual QSlider references
        self.edge_rate_slider = QSlider(Qt.Horizontal)
        self.edge_rate_slider.setRange(-50, 50)
        self.edge_rate_slider.setValue(self._parse_pct(self.config.get("edge_rate", "+0%")))
        self.edge_rate_lbl = QLabel(f"{self.edge_rate_slider.value():+d}%")
        self.edge_rate_slider.valueChanged.connect(
            lambda v: self.edge_rate_lbl.setText(f"{v:+d}%")
        )
        h_rate = QHBoxLayout()
        h_rate.addWidget(QLabel("Speed:"))
        h_rate.addWidget(self.edge_rate_slider, 1)
        h_rate.addWidget(self.edge_rate_lbl)
        ef.addRow(h_rate)

        self.edge_vol_slider = QSlider(Qt.Horizontal)
        self.edge_vol_slider.setRange(-50, 50)
        self.edge_vol_slider.setValue(self._parse_pct(self.config.get("edge_volume", "+0%")))
        self.edge_vol_lbl = QLabel(f"{self.edge_vol_slider.value():+d}%")
        self.edge_vol_slider.valueChanged.connect(
            lambda v: self.edge_vol_lbl.setText(f"{v:+d}%")
        )
        h_vol = QHBoxLayout()
        h_vol.addWidget(QLabel("Volume:"))
        h_vol.addWidget(self.edge_vol_slider, 1)
        h_vol.addWidget(self.edge_vol_lbl)
        ef.addRow(h_vol)

        self.edge_pitch_slider = QSlider(Qt.Horizontal)
        self.edge_pitch_slider.setRange(-50, 50)
        self.edge_pitch_slider.setValue(self._parse_hz(self.config.get("edge_pitch", "+0Hz")))
        self.edge_pitch_lbl = QLabel(f"{self.edge_pitch_slider.value():+d}Hz")
        self.edge_pitch_slider.valueChanged.connect(
            lambda v: self.edge_pitch_lbl.setText(f"{v:+d}Hz")
        )
        h_pitch = QHBoxLayout()
        h_pitch.addWidget(QLabel("Pitch:"))
        h_pitch.addWidget(self.edge_pitch_slider, 1)
        h_pitch.addWidget(self.edge_pitch_lbl)
        ef.addRow(h_pitch)

        self.backend_stack.addWidget(edge_page)

        # ── Qwen page ──
        qwen_page = QWidget()
        qf = QFormLayout(qwen_page)

        self.qwen_voice_combo = QComboBox()
        self.qwen_voice_combo.setEditable(True)
        self.qwen_voice_combo.addItems([
            "Cherry", "Serena", "Ethan", "Chelsie", "Echo", "Bonnie",
        ])
        self.qwen_voice_combo.setCurrentText(self.config.get("qwen_voice", "Serena"))
        qf.addRow("Voice:", self.qwen_voice_combo)

        self.qwen_rate_slider = QSlider(Qt.Horizontal)
        self.qwen_rate_slider.setRange(-50, 50)
        qwen_speed = self.config.get("qwen_speed", 1.0)
        self.qwen_rate_slider.setValue(int((qwen_speed - 1.0) * 100))
        self.qwen_rate_lbl = QLabel(f"{self.qwen_rate_slider.value():+d}%")
        self.qwen_rate_slider.valueChanged.connect(
            lambda v: self.qwen_rate_lbl.setText(f"{v:+d}%")
        )
        h_qrate = QHBoxLayout()
        h_qrate.addWidget(QLabel("Speed:"))
        h_qrate.addWidget(self.qwen_rate_slider, 1)
        h_qrate.addWidget(self.qwen_rate_lbl)
        qf.addRow(h_qrate)

        self.qwen_status = QLabel()
        self._update_qwen_status()
        qf.addRow(self.qwen_status)

        self.backend_stack.addWidget(qwen_page)

        tts_layout.addWidget(self.backend_stack)
        root.addWidget(grp_tts)
        self._on_backend_changed()

        # ══════════════════════════════════════════════════════════
        # 3. OUTPUT
        # ══════════════════════════════════════════════════════════
        grp_out = QGroupBox("3. Output")
        of = QFormLayout(grp_out)

        self.out_name = QLineEdit()
        self.out_name.setPlaceholderText("Auto-filled from source")
        of.addRow("Filename:", self.out_name)

        h_dir = QHBoxLayout()
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText(f"Auto: {self.default_output_dir}")
        self.out_dir.setText(self.config.get("output_dir", ""))
        self.out_dir.textChanged.connect(self._auto_name)
        btn_dir = QPushButton("📁 Folder")
        btn_dir.clicked.connect(self._browse_dir)
        h_dir.addWidget(self.out_dir, 1)
        h_dir.addWidget(btn_dir)
        of.addRow("Directory:", h_dir)

        h_fmt = QHBoxLayout()
        self.chk_mp3 = QCheckBox("MP3")
        self.chk_wav = QCheckBox("WAV")
        self.chk_m4b = QCheckBox("M4B (Audiobook)")
        fmt = self.config.get("output_format", "mp3")
        self.chk_mp3.setChecked(fmt in ("mp3", "both", "all"))
        self.chk_wav.setChecked(fmt in ("wav", "both", "all"))
        self.chk_m4b.setChecked(fmt in ("m4b", "all"))
        h_fmt.addWidget(self.chk_mp3)
        h_fmt.addWidget(self.chk_wav)
        h_fmt.addWidget(self.chk_m4b)
        h_fmt.addStretch()
        of.addRow("Format:", h_fmt)

        root.addWidget(grp_out)

        # ══════════════════════════════════════════════════════════
        # 4. QUALITY
        # ══════════════════════════════════════════════════════════
        grp_qual = QGroupBox("4. Quality & Processing")
        ql = QFormLayout(grp_qual)

        self.chk_normalize = QCheckBox("EBU R128 loudness normalization (−16 LUFS)")
        self.chk_normalize.setChecked(self.config.get("normalize_audio", True))
        self.chk_normalize.setToolTip(
            "Professional loudness normalization matching audiobook "
            "industry standards. Ensures consistent volume throughout."
        )
        ql.addRow(self.chk_normalize)

        self.chk_trim = QCheckBox("Trim inter-chunk silence")
        self.chk_trim.setChecked(self.config.get("trim_silence", True))
        self.chk_trim.setToolTip(
            "Removes excessive silence between audio chunks "
            "and adds natural 150ms pauses."
        )
        ql.addRow(self.chk_trim)

        self.chk_chapters = QCheckBox("Chapter-aware generation")
        self.chk_chapters.setChecked(self.config.get("chapter_aware", True))
        self.chk_chapters.setToolTip(
            "Automatically detects chapter breaks and generates "
            "chapter markers in M4B output."
        )
        ql.addRow(self.chk_chapters)

        root.addWidget(grp_qual)

        # ══════════════════════════════════════════════════════════
        # 5. PERFORMANCE
        # ══════════════════════════════════════════════════════════
        grp_perf = QGroupBox("5. Performance")
        pf = QFormLayout(grp_perf)

        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 50)
        self.spin_workers.setValue(self.config.get("concurrency", 15))
        self.spin_workers.setToolTip(
            "Number of parallel TTS requests. "
            "Edge TTS: 10-20 is safe. Qwen API: respect your rate limits."
        )
        pf.addRow("Parallel Workers:", self.spin_workers)

        self.spin_chunk = QSpinBox()
        self.spin_chunk.setRange(100, 3000)
        self.spin_chunk.setSingleStep(50)
        self.spin_chunk.setValue(self.config.get("chunk_size", 500))
        self.spin_chunk.setToolTip(
            "Characters per TTS chunk. 400-600 gives natural sentence "
            "boundaries. Larger chunks = fewer API calls but less natural pauses."
        )
        pf.addRow("Chunk Size (chars):", self.spin_chunk)

        root.addWidget(grp_perf)

        # ══════════════════════════════════════════════════════════
        # 6. ACTION BUTTONS
        # ══════════════════════════════════════════════════════════
        h_actions = QHBoxLayout()

        self.btn_preview = QPushButton("🔊 Preview Voice")
        self.btn_preview.setObjectName("previewBtn")
        self.btn_preview.clicked.connect(self._preview)
        h_actions.addWidget(self.btn_preview)

        self.btn_start = QPushButton("🚀 Produce Audiobook")
        self.btn_start.setObjectName("startBtn")
        self.btn_start.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_start.clicked.connect(self._start)
        h_actions.addWidget(self.btn_start, 1)

        self.btn_cancel = QPushButton("✖ Cancel")
        self.btn_cancel.setObjectName("cancelBtn")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel)
        h_actions.addWidget(self.btn_cancel)

        root.addLayout(h_actions)

        # ══════════════════════════════════════════════════════════
        # 7. STATUS
        # ══════════════════════════════════════════════════════════
        self.pbar = QProgressBar()
        self.pbar.setValue(0)
        root.addWidget(self.pbar)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("statusLabel")
        root.addWidget(self.status_lbl)

        self.log_console = QTextEdit()
        self.log_console.setObjectName("logConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(160)
        root.addWidget(self.log_console)

        self._auto_name()

    # ═════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════

    @staticmethod
    def _parse_pct(s):
        try:
            return int(str(s).replace("%", "").replace("+", ""))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_hz(s):
        try:
            return int(str(s).replace("Hz", "").replace("+", ""))
        except (ValueError, TypeError):
            return 0

    def _get_out_dir(self):
        d = self.out_dir.text().strip()
        return d if d else self.default_output_dir

    def _unique_name(self, directory, base):
        safe = re.sub(r'[\\/*?:"<>|]', "", base)[:50]
        name = safe
        c = 1
        while os.path.exists(os.path.join(directory, f"{name}.mp3")):
            name = f"{safe}_{c}"
            c += 1
        return name

    def _auto_name(self):
        is_raw = self.input_tabs.currentIndex() == 1
        out_dir = self._get_out_dir()
        if not is_raw:
            fp = self.file_edit.text().strip()
            base = os.path.splitext(os.path.basename(fp))[0] if fp else "Untitled"
        else:
            raw = self.raw_text.toPlainText().strip()
            first = raw.split("\n")[0] if raw else "New_Text"
            base = re.sub(r'[\\/*?:"<>|]', "", first)[:40]
        self.out_name.setText(self._unique_name(out_dir, base))

    def _fmt_string(self):
        mp3 = self.chk_mp3.isChecked()
        wav = self.chk_wav.isChecked()
        m4b = self.chk_m4b.isChecked()
        if m4b and mp3 and wav:
            return "all"
        if m4b and mp3:
            return "all"
        if m4b:
            return "m4b"
        if mp3 and wav:
            return "both"
        if mp3:
            return "mp3"
        if wav:
            return "wav"
        return "mp3"

    def _build_job_config(self):
        bid = self.backend_combo.currentData()
        cfg = {
            "backend": bid,
            "concurrency": self.spin_workers.value(),
            "chunk_size": self.spin_chunk.value(),
            "output_format": self._fmt_string(),
            "normalize_audio": self.chk_normalize.isChecked(),
            "trim_silence": self.chk_trim.isChecked(),
            "chapter_aware": self.chk_chapters.isChecked(),
        }
        if bid == "edge_tts":
            cfg["edge_voice"] = self.edge_voice_combo.currentText()
            cfg["edge_rate"] = f"{self.edge_rate_slider.value():+d}%"
            cfg["edge_volume"] = f"{self.edge_vol_slider.value():+d}%"
            cfg["edge_pitch"] = f"{self.edge_pitch_slider.value():+d}Hz"
        elif bid == "qwen_omnivoice":
            cfg["qwen_voice"] = self.qwen_voice_combo.currentText()
            cfg["qwen_speed"] = 1.0 + self.qwen_rate_slider.value() / 100.0
            cfg["qwen_api_key"] = self.config.get("qwen_api_key", "")
            cfg["qwen_model"] = self.config.get("qwen_model", "cosyvoice-v2")
            cfg["qwen_base_url"] = self.config.get(
                "qwen_base_url",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        return cfg

    def _save_current_config(self):
        self.config["backend"] = self.backend_combo.currentData()
        self.config["edge_voice"] = self.edge_voice_combo.currentText()
        self.config["edge_rate"] = f"{self.edge_rate_slider.value():+d}%"
        self.config["edge_volume"] = f"{self.edge_vol_slider.value():+d}%"
        self.config["edge_pitch"] = f"{self.edge_pitch_slider.value():+d}Hz"
        self.config["qwen_voice"] = self.qwen_voice_combo.currentText()
        self.config["concurrency"] = self.spin_workers.value()
        self.config["chunk_size"] = self.spin_chunk.value()
        self.config["output_format"] = self._fmt_string()
        self.config["output_dir"] = self.out_dir.text()
        self.config["last_file"] = self.file_edit.text()
        self.config["normalize_audio"] = self.chk_normalize.isChecked()
        self.config["trim_silence"] = self.chk_trim.isChecked()
        self.config["chapter_aware"] = self.chk_chapters.isChecked()
        save_config(self.config)

    def _update_qwen_status(self):
        key = self.config.get("qwen_api_key", "")
        model = self.config.get("qwen_model", "")
        if key:
            self.qwen_status.setText(
                f'<font color="#a6e3a1">✓ API key set</font>  •  Model: <b>{model}</b>'
            )
        else:
            self.qwen_status.setText(
                '<font color="#f38ba8">✗ No API key</font> — click ⚙ Configure'
            )

    # ═════════════════════════════════════════════════════════════
    # SLOTS
    # ═════════════════════════════════════════════════════════════

    def _on_backend_changed(self):
        bid = self.backend_combo.currentData()
        if bid == "edge_tts":
            self.backend_stack.setCurrentIndex(0)
        elif bid == "qwen_omnivoice":
            self.backend_stack.setCurrentIndex(1)
            self._update_qwen_status()

    def _browse_file(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Open Document", "",
            "Documents (*.txt *.pdf *.docx *.md *.html *.htm *.epub)"
        )
        if f:
            self.file_edit.setText(f)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if d:
            self.out_dir.setText(d)

    def _open_voice_search(self):
        bid = self.backend_combo.currentData()
        backend = create_backend(bid, self.config)
        current = self.edge_voice_combo.currentText()
        dlg = VoiceSearchDialog(backend, current, self)
        if dlg.exec():
            voice = dlg.get_selected_voice()
            if voice:
                self.edge_voice_combo.setCurrentText(voice)

    def _open_backend_config(self):
        bid = self.backend_combo.currentData()
        if bid == "qwen_omnivoice":
            dlg = QwenConfigDialog(self.config, self)
            if dlg.exec():
                self.config.update(dlg.get_config())
                self._update_qwen_status()
        else:
            QMessageBox.information(
                self, "Edge TTS",
                "Edge TTS requires no additional configuration.\n"
                "It uses Microsoft's free cloud voices."
            )

    # ── Preview ─────────────────────────────────────────────────

    def _preview(self):
        is_raw = self.input_tabs.currentIndex() == 1
        if is_raw:
            text = self.raw_text.toPlainText().strip()
        else:
            fp = self.file_edit.text().strip()
            if fp and os.path.exists(fp):
                from text_processor import TextProcessor
                chunks = list(TextProcessor.chunk_generator(fp, 300, False))
                text = chunks[0] if chunks else ""
            else:
                text = ""

        if not text:
            QMessageBox.warning(self, "Preview", "No text available.")
            return

        text = text[:300]
        bid = self.backend_combo.currentData()
        job_cfg = self._build_job_config()

        self.btn_preview.setEnabled(False)
        self.log_console.append(
            f"<i>Generating preview with {self.backend_combo.currentText()}…</i>"
        )

        import tempfile
        import asyncio
        from tts_backends import create_backend

        preview_file = os.path.join(tempfile.gettempdir(), "audiobook_preview.mp3")

        class _PreviewThread(QThread):
            done = Signal(bool, str)

            def __init__(self, backend, text, path, voice):
                super().__init__()
                self.backend = backend
                self.text = text
                self.path = path
                self.voice = voice

            def run(self):
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        self.backend.preview(self.text, self.path, self.voice)
                    )
                    self.done.emit(True, self.path)
                except Exception as e:
                    self.done.emit(False, str(e))
                finally:
                    try:
                        loop.run_until_complete(self.backend.close())
                    except Exception:
                        pass
                    loop.close()

        backend = create_backend(bid, job_cfg)
        voice = (
            job_cfg.get("edge_voice", "en-US-AvaNeural")
            if bid == "edge_tts"
            else job_cfg.get("qwen_voice", "Serena")
        )
        self._preview_thread = _PreviewThread(backend, text, preview_file, voice)
        self._preview_thread.done.connect(self._on_preview_done)
        self._preview_thread.start()

    def _on_preview_done(self, success, result):
        self.btn_preview.setEnabled(True)
        if success:
            self.log_console.append('<font color="#a6e3a1">✓ Preview ready — playing…</font>')
            self._play_file(result)
        else:
            self.log_console.append(f'<font color="red">Preview failed: {result}</font>')

    def _play_file(self, path):
        if not os.path.exists(path):
            return
        if self._media_player:
            self._media_player.stop()
        audio_out = QAudioOutput()
        self._media_player = QMediaPlayer()
        self._media_player.setAudioOutput(audio_out)
        self._media_player.setSource(QUrl.fromLocalFile(path))
        audio_out.setVolume(0.8)
        self._media_player.play()

    # ── Production ──────────────────────────────────────────────

    def _start(self):
        is_raw = self.input_tabs.currentIndex() == 1
        source = self.raw_text.toPlainText().strip() if is_raw else self.file_edit.text().strip()

        if is_raw and not source:
            QMessageBox.warning(self, "Error", "Please enter text to convert.")
            return
        if not is_raw and (not source or not os.path.exists(source)):
            QMessageBox.warning(self, "Error", "Please select a valid input file.")
            return

        job_cfg = self._build_job_config()

        # Pre-flight validation
        backend = create_backend(job_cfg["backend"], job_cfg)
        errors = backend.validate_config()
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(backend.close())
            loop.close()
        except Exception:
            pass

        if errors:
            QMessageBox.critical(
                self, "Configuration Error",
                "Please fix:\n\n• " + "\n• ".join(errors)
            )
            return

        out_dir = self._get_out_dir()
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Cannot create output directory:\n{e}")
            return

        out_name = self.out_name.text() or "Audiobook"
        full_out = os.path.join(out_dir, out_name)

        self._save_current_config()
        self.log_console.clear()
        self.pbar.setValue(0)
        self.status_lbl.setText("Starting…")

        self.btn_start.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        # Choose engine
        if job_cfg.get("chapter_aware", True):
            self.engine = ChapterEngine(
                source, full_out, job_cfg,
                is_raw_text=is_raw,
                enable_ssml=False,
                trim_silence=job_cfg.get("trim_silence", True),
            )
        else:
            self.engine = AudioEngine(source, full_out, job_cfg, is_raw_text=is_raw)

        self.engine.progress.connect(self._on_progress)
        self.engine.log.connect(lambda s: self.log_console.append(s))
        self.engine.finished.connect(self._on_finished)

        # Connect chapter progress if ChapterEngine
        if isinstance(self.engine, ChapterEngine):
            self.engine.chapter_progress.connect(self._on_chapter_progress)

        self.engine.start()

    def _cancel(self):
        if self.engine:
            self.engine.cancel()

    def _on_progress(self, pct, txt):
        self.pbar.setValue(pct)
        self.status_lbl.setText(txt)

    def _on_chapter_progress(self, current, total):
        self.log_console.append(
            f'<b>📖 Processing chapter {current}/{total}</b>'
        )

    def _on_finished(self, success, msg):
        self.btn_start.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.btn_cancel.setEnabled(False)

        if success:
            self.pbar.setValue(100)
            self.status_lbl.setText("✓ Complete!")
            self.log_console.append(msg)
            QMessageBox.information(self, "Audiobook Complete", msg)
            if self.input_tabs.currentIndex() == 1:
                self._auto_name()
        else:
            self.status_lbl.setText("✗ Failed")
            self.log_console.append(f'<font color="red"><b>Error:</b> {msg}</font>')
            QMessageBox.critical(self, "Production Error", msg)