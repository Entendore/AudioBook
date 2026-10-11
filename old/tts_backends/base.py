from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class VoiceInfo:
    """Normalized voice descriptor across all backends."""
    id: str
    name: str
    locale: str
    gender: str

    def display(self) -> str:
        return f"{self.name}  ({self.gender}, {self.locale})"


class TTSBackend(ABC):
    """Abstract base for all TTS backends."""

    def __init__(self, config: dict):
        self.config = config

    # ── Core interface ──────────────────────────────────────────

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice: str,
        rate: str,
        volume: str,
        pitch: str,
    ) -> bool:
        """Generate audio for *text* and write to *output_path*. Return True on success."""
        ...

    @abstractmethod
    async def list_voices(self) -> List[VoiceInfo]:
        """Return available voices."""
        ...

    # ── Metadata ────────────────────────────────────────────────

    @property
    @abstractmethod
    def display_name(self) -> str: ...

    @property
    @abstractmethod
    def backend_id(self) -> str: ...

    @property
    @abstractmethod
    def default_output_format(self) -> str: ...

    @property
    def supports_pitch(self) -> bool:
        return True

    @property
    def supports_volume(self) -> bool:
        return True

    @property
    def supports_rate(self) -> bool:
        return True

    # ── Validation ──────────────────────────────────────────────

    def validate_config(self) -> List[str]:
        """Return a list of error strings; empty = valid."""
        return []

    # ── Lifecycle ───────────────────────────────────────────────

    async def close(self):
        """Release resources (HTTP sessions, etc.). Override if needed."""
        pass

    async def preview(self, text: str, output_path: str, voice: str) -> bool:
        """Quick preview — defaults to synthesize with neutral params."""
        return await self.synthesize(
            text, output_path, voice, "+0%", "+0%", "+0Hz"
        )