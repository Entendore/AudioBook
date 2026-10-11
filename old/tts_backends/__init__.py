from typing import Dict, Type

from .base import TTSBackend
from .edge_tts_backend import EdgeTTSBackend
from .qwen_backend import QwenBackend

BACKEND_REGISTRY: Dict[str, Type[TTSBackend]] = {
    "edge_tts": EdgeTTSBackend,
    "qwen_omnivoice": QwenBackend,
}


def create_backend(backend_id: str, config: dict) -> TTSBackend:
    """Factory: instantiate a TTS backend from config."""
    cls = BACKEND_REGISTRY.get(backend_id)
    if cls is None:
        raise ValueError(
            f"Unknown backend '{backend_id}'. "
            f"Available: {list(BACKEND_REGISTRY.keys())}"
        )
    return cls(config)


def get_available_backends() -> dict:
    """Return {id: display_name} for UI."""
    return {bid: cls(config={}).display_name for bid, cls in BACKEND_REGISTRY.items()}