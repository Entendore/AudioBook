import asyncio
import edge_tts
from PySide6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QDialogButtonBox

class VoiceSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find Voices")
        self.resize(400, 500)
        layout = QVBoxLayout(self)
        
        self.list_widget = QListWidget()
        self.list_widget.setSortingEnabled(True)
        layout.addWidget(self.list_widget)
        
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        
        self.load_voices()

    def load_voices(self):
        try:
            # Blocking call, usually fast
            voices = asyncio.run(edge_tts.list_voices())
            for v in voices:
                name = v['ShortName']
                gender = v['Gender']
                locale = v['Locale']
                self.list_widget.addItem(f"{name} ({gender}, {locale})")
        except Exception:
            self.list_widget.addItem("Error loading voices (check internet)")

    def get_selected_voice(self):
        item = self.list_widget.currentItem()
        if item:
            return item.text().split(' ')[0]
        return None