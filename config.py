"""Application configuration — dataclass-based with validation and persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("audiobook_config.json")


@dataclass
class AppConfig:
    """Mutable application configuration persisted to disk."""

    # ── Backend selection ───────────────────────────────────────
    backend: str = "edge_tts"

    # ── Edge TTS ────────────────────────────────────────────────
    edge_voice: str = "en-US-AvaNeural"
    edge_rate: str = "+0%"
    edge_volume: str = "+0%"
    edge_pitch: str = "+0Hz"

    # ── Local Qwen TTS ──────────────────────────────────────────
    qwen_model_path: str = "Qwen/Qwen2.5-3B" # HuggingFace repo ID or local path
    qwen_device: str = "cuda" # "cuda" or "cpu"
    qwen_voice: str = "Cherry"

    # ── Local OmniVoice TTS ─────────────────────────────────────
    omnivoice_model_path: str = "OmniVoice/OmniVoice-TTS" # HuggingFace repo ID or local path
    omnivoice_device: str = "cuda"
    omnivoice_speaker_id: int = 0

    # ── General ─────────────────────────────────────────────────
    concurrency: int = 5
    chunk_size: int = 500
    output_format: str = "mp3"
    output_dir: str = ""
    last_file: str = ""
    normalize_audio: bool = True
    trim_silence: bool = True
    chapter_aware: bool = True
    multi_speaker: bool = False
    voice_map: Dict[str, str] = field(default_factory=dict)

    # ── Metadata / Cover ────────────────────────────────────────
    book_title: str = ""
    book_author: str = ""
    cover_art: str = ""

    # ── Window geometry ─────────────────────────────────────────
    window_width: int = 880
    window_height: int = 980

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AppConfig:
        valid = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid}
        return cls(**filtered)

    def save(self, path: Path = CONFIG_PATH) -> None:
        try:
            path.write_text(
                json.dumps(self.to_dict(), indent=4, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save config: %s", exc)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> AppConfig:
        if path.exists():
            try:
                return cls.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except Exception as exc:
                logger.warning("Failed to load config: %s — using defaults", exc)
        return cls()


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Immutable snapshot passed to the pipeline.  Thread-safe."""

    backend_id: str
    voice: str
    rate: str
    volume: str
    pitch: str
    concurrency: int
    chunk_size: int
    output_format: str
    normalize: bool
    trim_silence: bool
    chapter_aware: bool
    multi_speaker: bool
    voice_map: Dict[str, str]
    title: str = "Audiobook"
    author: str = "Unknown"
    cover_art: str = ""
    # Local Model Configs
    qwen_model_path: str = ""
    qwen_device: str = "cuda"
    omnivoice_model_path: str = ""
    omnivoice_device: str = "cuda"
    omnivoice_speaker_id: int = 0

    @classmethod
    def from_app_config(cls, app: AppConfig) -> EngineConfig:
        bid = app.backend
        if bid == "qwen_local":
            voice = app.qwen_voice
            rate, volume, pitch = "+0%", "+0%", "+0Hz"
        elif bid == "omnivoice_local":
            voice = str(app.omnivoice_speaker_id)
            rate, volume, pitch = "+0%", "+0%", "+0Hz"
        else:
            voice = app.edge_voice
            rate = app.edge_rate
            volume = app.edge_volume
            pitch = app.edge_pitch

        return cls(
            backend_id=bid, voice=voice, rate=rate, volume=volume, pitch=pitch,
            concurrency=app.concurrency, chunk_size=app.chunk_size,
            output_format=app.output_format, normalize=app.normalize_audio,
            trim_silence=app.trim_silence, chapter_aware=app.chapter_aware,
            multi_speaker=app.multi_speaker, voice_map=app.voice_map,
            title=app.book_title or "Audiobook", author=app.book_author or "Unknown",
            cover_art=app.cover_art,
            qwen_model_path=app.qwen_model_path, qwen_device=app.qwen_device,
            omnivoice_model_path=app.omnivoice_model_path, omnivoice_device=app.omnivoice_device,
            omnivoice_speaker_id=app.omnivoice_speaker_id,
        )