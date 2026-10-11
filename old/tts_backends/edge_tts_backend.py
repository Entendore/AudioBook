import asyncio
from typing import List

import edge_tts

from .base import TTSBackend, VoiceInfo


class EdgeTTSBackend(TTSBackend):
    """Microsoft Edge TTS — free, fast, high-quality cloud voices."""

    @property
    def display_name(self) -> str:
        return "Edge TTS (Microsoft)"

    @property
    def backend_id(self) -> str:
        return "edge_tts"

    @property
    def default_output_format(self) -> str:
        return "mp3"

    @property
    def supports_pitch(self) -> bool:
        return True

    @property
    def supports_volume(self) -> bool:
        return True

    # ── Synthesis ───────────────────────────────────────────────

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice: str = "en-US-AvaNeural",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> bool:
        try:
            communicate = edge_tts.Communicate(
                text, voice, rate=rate, volume=volume, pitch=pitch
            )
            await asyncio.wait_for(communicate.save(output_path), timeout=120.0)
            return True
        except asyncio.TimeoutError:
            raise TimeoutError(f"Edge TTS timed out for chunk")
        except Exception as e:
            raise RuntimeError(f"Edge TTS error: {e}")

    # ── Voice listing ───────────────────────────────────────────

    async def list_voices(self) -> List[VoiceInfo]:
        try:
            raw = await edge_tts.list_voices()
            return [
                VoiceInfo(
                    id=v["ShortName"],
                    name=v["FriendlyName"][:40],
                    locale=v["Locale"],
                    gender=v["Gender"],
                )
                for v in raw
            ]
        except Exception:
            return []

    # ── Validation ──────────────────────────────────────────────

    def validate_config(self) -> List[str]:
        errors = []
        if not self.config.get("edge_voice"):
            errors.append("No voice selected for Edge TTS.")
        return errors