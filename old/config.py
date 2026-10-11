import os
import json

CONFIG_FILE = "audiobook_config.json"

DEFAULT_CONFIG = {
    "backend": "edge_tts",

    # Edge TTS settings
    "edge_voice": "en-US-AvaNeural",
    "edge_rate": "+0%",
    "edge_volume": "+0%",
    "edge_pitch": "+0Hz",

    # Qwen3 OmniVoice settings
    "qwen_api_key": "",
    "qwen_model": "cosyvoice-v2",
    "qwen_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_voice": "Serena",
    "qwen_speed": 1.0,

    # General settings
    "concurrency": 15,
    "chunk_size": 500,
    "output_format": "mp3",
    "output_dir": "",
    "last_file": "",
    "normalize_audio": True,
    "add_metadata": True,
    "quality_preset": "standard",
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(saved)
            return merged
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config_data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")