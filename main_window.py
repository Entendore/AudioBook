import os
import re
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QComboBox, QFileDialog, QProgressBar, 
    QMessageBox, QTextEdit, QGroupBox, QSpinBox, QSlider, QCheckBox, 
    QFormLayout, QTabWidget
)
from PySide6.QtCore import Qt
from config import load_config, save_config
from audio_engine import AudioEngine
from dialogs import VoiceSearchDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Advanced Audiobook Studio")
        self.setGeometry(100, 100, 800, 800)
        
        self.config = load_config()
        self.engine = None
        
        # Define default output folder
        self.default_output_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "output")
        
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # --- 1. Input Section (Tabs) ---
        self.input_tabs = QTabWidget()
        
        # Tab 1: File Input
        file_tab = QWidget()
        fl_file = QHBoxLayout(file_tab)
        self.file_edit = QLineEdit()
        self.file_edit.setText(self.config.get('last_file', ''))
        self.file_edit.setPlaceholderText("Select PDF, TXT, DOCX, EPUB...") # Updated placeholder
        self.file_edit.textChanged.connect(self.update_auto_output_name)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_file)
        fl_file.addWidget(self.file_edit); fl_file.addWidget(btn_browse)
        
        # Tab 2: Text Input
        text_tab = QWidget()
        fl_text = QVBoxLayout(text_tab)
        self.raw_text_edit = QTextEdit()
        self.raw_text_edit.setPlaceholderText("Paste your text here...")
        self.raw_text_edit.textChanged.connect(self.update_auto_output_name)
        fl_text.addWidget(self.raw_text_edit)

        self.input_tabs.addTab(file_tab, "From File")
        self.input_tabs.addTab(text_tab, "Paste Text")
        main_layout.addWidget(self.input_tabs)

        # --- 2. TTS Settings ---
        group_tts = QGroupBox("2. Voice & Speech Settings")
        form_tts = QFormLayout(group_tts)
        
        # Voice
        h_voice = QHBoxLayout()
        self.voice_combo = QComboBox()
        self.voice_combo.setEditable(True)
        self.voice_combo.addItems(["en-US-AvaNeural", "en-US-AndrewNeural", "en-GB-SoniaNeural", "en-GB-RyanNeural"])
        self.voice_combo.setCurrentText(self.config.get('voice', ''))
        btn_search = QPushButton("Search All Voices")
        btn_search.clicked.connect(self.open_voice_search)
        h_voice.addWidget(self.voice_combo); h_voice.addWidget(btn_search)
        
        # Speed Slider
        h_rate = QHBoxLayout()
        self.rate_slider = QSlider(Qt.Horizontal)
        self.rate_slider.setRange(-50, 50)
        val = int(str(self.config.get('rate', '+0%')).replace('%','').replace('+',''))
        self.rate_slider.setValue(val)
        self.rate_lbl = QLabel(f"{val}%")
        self.rate_slider.valueChanged.connect(lambda v: self.rate_lbl.setText(f"{v}%"))
        h_rate.addWidget(QLabel("Speed:")); h_rate.addWidget(self.rate_slider); h_rate.addWidget(self.rate_lbl)

        # Volume Slider
        h_vol = QHBoxLayout()
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(-50, 50)
        val = int(str(self.config.get('volume', '+0%')).replace('%','').replace('+',''))
        self.vol_slider.setValue(val)
        self.vol_lbl = QLabel(f"{val}%")
        self.vol_slider.valueChanged.connect(lambda v: self.vol_lbl.setText(f"{v}%"))
        h_vol.addWidget(QLabel("Volume:")); h_vol.addWidget(self.vol_slider); h_vol.addWidget(self.vol_lbl)

        # Pitch Slider
        h_pitch = QHBoxLayout()
        self.pitch_slider = QSlider(Qt.Horizontal)
        self.pitch_slider.setRange(-50, 50)
        val = 0
        try:
            val = int(str(self.config.get('pitch', '+0Hz')).replace('Hz','').replace('+',''))
        except: val = 0
        self.pitch_slider.setValue(val)
        self.pitch_lbl = QLabel(f"{val}Hz")
        self.pitch_slider.valueChanged.connect(lambda v: self.pitch_lbl.setText(f"{v}Hz"))
        h_pitch.addWidget(QLabel("Pitch:")); h_pitch.addWidget(self.pitch_slider); h_pitch.addWidget(self.pitch_lbl)

        form_tts.addRow("Voice:", h_voice)
        form_tts.addRow(h_rate)
        form_tts.addRow(h_vol)
        form_tts.addRow(h_pitch)
        main_layout.addWidget(group_tts)

        # --- 3. Output Settings ---
        group_out = QGroupBox("3. Output Settings")
        fl_out = QFormLayout(group_out)
        
        self.out_name_edit = QLineEdit() 
        self.out_name_edit.setPlaceholderText("Auto-filled based on input")
        
        h_dir = QHBoxLayout()
        self.out_dir_edit = QLineEdit()
        # Set placeholder to indicate automatic behavior
        self.out_dir_edit.setPlaceholderText(f"Auto: {self.default_output_dir}")
        self.out_dir_edit.setText(self.config.get('output_dir', ''))
        self.out_dir_edit.textChanged.connect(self.update_auto_output_name)
        btn_out_dir = QPushButton("Folder")
        btn_out_dir.clicked.connect(self.browse_dir)
        h_dir.addWidget(self.out_dir_edit); h_dir.addWidget(btn_out_dir)
        
        h_fmt = QHBoxLayout()
        self.chk_mp3 = QCheckBox("MP3")
        self.chk_wav = QCheckBox("WAV")
        fmt = self.config.get('output_format', 'both')
        self.chk_mp3.setChecked(fmt in ['mp3', 'both'])
        self.chk_wav.setChecked(fmt in ['wav', 'both'])
        h_fmt.addWidget(self.chk_mp3); h_fmt.addWidget(self.chk_wav)
        
        fl_out.addRow("Filename:", self.out_name_edit)
        fl_out.addRow("Output Dir:", h_dir)
        fl_out.addRow("Format:", h_fmt)
        main_layout.addWidget(group_out)

        # --- 4. Performance ---
        group_perf = QGroupBox("4. Performance (Advanced)")
        fl_perf = QFormLayout(group_perf)
        
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 50)
        self.spin_workers.setValue(self.config.get('concurrency', 15))
        
        self.spin_chunk = QSpinBox()
        self.spin_chunk.setRange(100, 2000)
        self.spin_chunk.setSingleStep(50)
        self.spin_chunk.setValue(self.config.get('chunk_size', 500))
        
        fl_perf.addRow("Parallel Workers:", self.spin_workers)
        fl_perf.addRow("Chunk Size (chars):", self.spin_chunk)
        main_layout.addWidget(group_perf)

        # --- 5. Controls ---
        self.btn_start = QPushButton("🚀 Start Production")
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-size: 16px; padding: 10px;")
        self.btn_start.clicked.connect(self.start_production)
        main_layout.addWidget(self.btn_start)

        # --- 6. Status ---
        self.pbar = QProgressBar()
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(100)
        main_layout.addWidget(self.pbar)
        main_layout.addWidget(self.log_console)

        # Initial Auto-Name Update
        self.update_auto_output_name()

    def get_output_directory(self):
        """
        Returns the effective output directory.
        If the input field is empty, returns the default 'output' folder.
        """
        dir_path = self.out_dir_edit.text().strip()
        if not dir_path:
            return self.default_output_dir
        return dir_path

    def get_unique_filename(self, directory, base_name):
        """
        Generates a unique filename. If file exists, appends _1, _2, etc.
        """
        safe_base = re.sub(r'[\\/*?:"<>|]', "", base_name)
        safe_base = safe_base[:50]
        
        potential_name = safe_base
        counter = 1
        
        # Check if file exists in the determined directory
        while os.path.exists(os.path.join(directory, f"{potential_name}.mp3")):
            potential_name = f"{safe_base}_{counter}"
            counter += 1
            
        return potential_name

    def update_auto_output_name(self):
        """
        Automatically sets the output filename. 
        """
        text = ""
        is_raw_text = self.input_tabs.currentIndex() == 1
        
        # Get the effective directory
        out_dir = self.get_output_directory()

        if not is_raw_text: # File Tab
            filepath = self.file_edit.text().strip()
            if filepath:
                text = os.path.splitext(os.path.basename(filepath))[0]
            else:
                text = "Untitled_File"
            self.out_name_edit.setText(text)
        else: # Text Tab
            raw = self.raw_text_edit.toPlainText().strip()
            if raw:
                first_line = raw.split('\n')[0]
                safe_name = re.sub(r'[\\/*?:"<>|]', "", first_line)
                base_name = safe_name[:40]
                
                unique_name = self.get_unique_filename(out_dir, base_name)
                self.out_name_edit.setText(unique_name)
            else:
                self.out_name_edit.setText("New_Text")

    def browse_file(self):
        # UPDATED: Added *.epub to the filter
        f, _ = QFileDialog.getOpenFileName(self, "Open", "", "Docs (*.txt *.pdf *.docx *.md *.html *.epub)")
        if f:
            self.file_edit.setText(f)

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if d:
            self.out_dir_edit.setText(d)

    def open_voice_search(self):
        dlg = VoiceSearchDialog(self)
        if dlg.exec():
            voice = dlg.get_selected_voice()
            if voice:
                self.voice_combo.setCurrentText(voice)

    def get_format_string(self):
        mp3 = self.chk_mp3.isChecked()
        wav = self.chk_wav.isChecked()
        if mp3 and wav: return 'both'
        if mp3: return 'mp3'
        if wav: return 'wav'
        return 'both'

    def start_production(self):
        # Determine source
        is_raw_text = self.input_tabs.currentIndex() == 1
        source = None
        
        if is_raw_text:
            source = self.raw_text_edit.toPlainText().strip()
            if not source:
                QMessageBox.warning(self, "Error", "Please enter some text.")
                return
        else:
            source = self.file_edit.text().strip()
            if not source or not os.path.exists(source):
                QMessageBox.warning(self, "Error", "Please select a valid input file.")
                return
        
        # Determine Output Path
        out_dir = self.get_output_directory() # Use the helper function
        
        # Create directory if it doesn't exist
        try:
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
                self.log_console.append(f"Created output directory: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create output directory:\n{e}")
            return
        
        out_name = self.out_name_edit.text()
        if not out_name: out_name = "Audiobook"
        
        full_out_path = os.path.join(out_dir, out_name)
        
        job_config = {
            "voice": self.voice_combo.currentText(),
            "rate": f"{self.rate_slider.value():+d}%",
            "volume": f"{self.vol_slider.value():+d}%",
            "pitch": f"{self.pitch_slider.value():+d}Hz",
            "concurrency": self.spin_workers.value(),
            "chunk_size": self.spin_chunk.value(),
            "output_format": self.get_format_string()
        }
        
        # Save Config
        current_cfg = {
            "voice": self.voice_combo.currentText(),
            "rate": f"{self.rate_slider.value():+d}%",
            "volume": f"{self.vol_slider.value():+d}%",
            "pitch": f"{self.pitch_slider.value():+d}Hz",
            "concurrency": self.spin_workers.value(),
            "chunk_size": self.spin_chunk.value(),
            "output_format": self.get_format_string(),
            "output_dir": self.out_dir_edit.text(), # Save user preference
            "last_file": self.file_edit.text()
        }
        save_config(current_cfg)
        
        self.log_console.clear()
        self.btn_start.setEnabled(False)
        
        self.engine = AudioEngine(source, full_out_path, job_config, is_raw_text=is_raw_text)
        self.engine.progress.connect(self.update_progress)
        self.engine.log.connect(lambda s: self.log_console.append(s))
        self.engine.finished.connect(self.production_finished)
        self.engine.start()

    def update_progress(self, val, txt):
        self.pbar.setValue(val)
        self.log_console.append(txt)

    def production_finished(self, success, msg):
        self.btn_start.setEnabled(True)
        if success:
            self.pbar.setValue(100)
            QMessageBox.information(self, "Done", msg)
            if self.input_tabs.currentIndex() == 1:
                self.update_auto_output_name()
        else:
            QMessageBox.critical(self, "Error", msg)
