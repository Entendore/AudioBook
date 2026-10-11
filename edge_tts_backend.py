"""
Edge TTS Backend — Microsoft's free cloud text-to-speech.

Requirements: ``pip install edge-tts``
"""

from __future__ import annotations

import logging
import xml.sax.saxutils as sax
from typing import List, Optional, Tuple

from tts_backends import TTSBackend, VoiceInfo

logger = logging.getLogger(__name__)


class EdgeTTSBackend(TTSBackend):
    """Microsoft Edge TTS — 400+ free cloud voices, no API key required. SSML Multi-Speaker."""

    id = "edge_tts"
    name = "Edge TTS (Free)"
    description = "400+ free cloud voices from Microsoft. No API key. SSML Multi-Speaker."

    def __init__(self, config: dict):
        super().__init__(config)
        self._communicate_cls: Optional[type] = None

    def _lazy_import(self):
        if self._communicate_cls is None:
            try:
                # Import the actual pip package
                import edge_tts as ms_edge_tts
                self._communicate_cls = ms_edge_tts.Communicate
            except ImportError:
                raise ImportError("pip install edge-tts")
        return self._communicate_cls

    @staticmethod
    def _escape_xml(text: str) -> str:
        return sax.escape(text, {'"': '&quot;', "'": '&apos;'})

    async def synthesize(
        self, text: str, output_path: str, voice: str = "",
        rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz",
    ) -> bool:
        voice = voice or self.config.get("edge_voice", "en-US-AvaNeural")
        cls = self._lazy_import()
        comm = cls(text, voice, rate=rate, volume=volume, pitch=pitch)
        await comm.save(output_path)
        return True

    async def synthesize_segments(
        self,
        segments: List[Tuple[str, str]],
        output_path: str,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> bool:
        """Generate SSML for seamless multi-speaker dialogue in one audio file."""
        if not segments:
            return False

        # If only one speaker, skip SSML to save overhead
        voices_in_chunk = {v for _, v in segments}
        if len(voices_in_chunk) == 1:
            return await self.synthesize(
                " ".join([t for t, _ in segments]), output_path, 
                voice=segments[0][1], rate=rate, volume=volume, pitch=pitch
            )

        # Build SSML
        ssml = (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
            f"<prosody rate='{rate}' volume='{volume}' pitch='{pitch}'>"
        )
        for text, voice_id in segments:
            escaped_text = self._escape_xml(text)
            ssml += f"<voice name='{voice_id}'>{escaped_text}</voice>"
        
        ssml += "</prosody></speak>"

        cls = self._lazy_import()
        # Pass SSML directly to Communicate
        comm = cls(ssml, voice=segments[0][1])
        await comm.save(output_path)
        return True

    async def list_voices(self) -> List[VoiceInfo]:
        try:
            import edge_tts as ms_edge_tts
        except ImportError:
            return []
        return [
            VoiceInfo(
                id=v["ShortName"], name=v["FriendlyName"],
                locale=v.get("Locale", ""), gender=v.get("Gender", ""),
            )
            for v in await ms_edge_tts.list_voices()
        ]

    def validate_config(self) -> List[str]:
        try:
            import edge_tts as ms_edge_tts  # noqa: F401
        except ImportError:
            return ["edge-tts not installed — run: pip install edge-tts"]
        return []

    async def preview(self, text: str, output_path: str, voice: str = "") -> bool:
        voice = voice or self.config.get("edge_voice", "en-US-AvaNeural")
        return await self.synthesize(
            text[:300], output_path, voice=voice,
            rate="+0%", volume="+0%", pitch="+0Hz",
        )