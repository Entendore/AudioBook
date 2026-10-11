"""
TTS Backend Plugin System
=========================

This file contains the abstract base class and the auto-registration registry.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Type

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VoiceInfo:
    id: str
    name: str
    locale: str = ""
    gender: str = ""

    def display(self) -> str:
        parts = [self.name]
        if self.locale: parts.append(f"({self.locale})")
        if self.gender: parts.append(f"[{self.gender}]")
        return " ".join(parts)


class TTSBackend(ABC):
    _registry: Dict[str, Type["TTSBackend"]] = {}

    id: str = ""
    name: str = ""
    description: str = ""

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if cls.id:
            TTSBackend._registry[cls.id] = cls
            logger.debug("Registered TTS backend: %s (%s)", cls.id, cls.name)

    @classmethod
    def create(cls, backend_id: str, config: dict) -> "TTSBackend":
        if backend_id not in cls._registry:
            avail = ", ".join(cls._registry) or "none"
            raise ValueError(f"Unknown backend '{backend_id}'. Available: {avail}")
        return cls._registry[backend_id](config)

    @classmethod
    def available(cls) -> Dict[str, str]:
        return {bid: bcls.name for bid, bcls in cls._registry.items()}

    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    async def synthesize(
        self, text: str, output_path: str, voice: str = "",
        rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz",
    ) -> bool: ...

    @abstractmethod
    async def list_voices(self) -> List[VoiceInfo]: ...

    @abstractmethod
    def validate_config(self) -> List[str]: ...

    async def synthesize_segments(
        self,
        segments: List[Tuple[str, str]],
        output_path: str,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> bool:
        if not segments:
            return False
        voice_counts: Dict[str, int] = {}
        for _, v in segments:
            voice_counts[v] = voice_counts.get(v, 0) + 1
        dominant_voice = max(voice_counts, key=voice_counts.get)
        full_text = " ".join([t for t, _ in segments])
        
        return await self.synthesize(
            full_text, output_path, voice=dominant_voice,
            rate=rate, volume=volume, pitch=pitch
        )

    async def preview(self, text: str, output_path: str, voice: str = "") -> bool:
        return await self.synthesize(text, output_path, voice=voice)

    async def close(self) -> None:
        pass


# ═══════════════════════════════════════════════════════════════════
# Import local backend files to trigger __init_subclass__ registration
# ═══════════════════════════════════════════════════════════════════
import edge_tts_backend           # noqa: E402, F401
import qwen_local_tts_backend     # noqa: E402, F401
import omnivoice_local_tts_backend # noqa: E402, F401