import os
import json

CONFIG_FILE = "audiobook_config.json"

DEFAULT_CONFIG = {
    "voice": "en-US-AvaNeural",
    "rate": "+0%",
    "volume": "+0%",
    "pitch": "+0Hz",
    "concurrency": 15,
    "chunk_size": 500,
    "output_format": "both",
    "output_dir": "",
    "last_file": ""
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config_data):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")