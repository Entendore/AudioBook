import asyncio
import json
from typing import List, Optional

from .base import TTSBackend, VoiceInfo

# Optional dependency — graceful degradation
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


class QwenBackend(TTSBackend):
    """Qwen3 OmniVoice / CosyVoice TTS via OpenAI-compatible API (DashScope or local)."""

    # Well-known voice presets
    VOICE_PRESETS = [
        VoiceInfo(id="Cherry",   name="Cherry",   locale="zh-CN", gender="Female"),
        VoiceInfo(id="Serena",   name="Serena",   locale="en-US", gender="Female"),
        VoiceInfo(id="Ethan",    name="Ethan",     locale="en-US", gender="Male"),
        VoiceInfo(id="Chelsie",  name="Chelsie",  locale="en-US", gender="Female"),
        VoiceInfo(id="Echo",     name="Echo",      locale="en-US", gender="Male"),
        VoiceInfo(id="Bonnie",   name="Bonnie",   locale="zh-CN", gender="Female"),
    ]

    def __init__(self, config: dict):
        super().__init__(config)
        self._session: Optional["aiohttp.ClientSession"] = None

    # ── Properties ──────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        return "Qwen3 OmniVoice"

    @property
    def backend_id(self) -> str:
        return "qwen_omnivoice"

    @property
    def default_output_format(self) -> str:
        return "mp3"

    @property
    def supports_pitch(self) -> bool:
        return False  # Qwen API doesn't expose pitch directly

    @property
    def supports_volume(self) -> bool:
        return False

    # ── Session management ──────────────────────────────────────

    async def _get_session(self) -> "aiohttp.ClientSession":
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for the Qwen backend. "
                "Install with: pip install aiohttp"
            )
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120, connect=10)
            )
        return self._session

    # ── Synthesis ───────────────────────────────────────────────

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice: str = "Serena",
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
    ) -> bool:
        session = await self._get_session()

        base_url = self.config.get(
            "qwen_base_url",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).rstrip("/")
        url = f"{base_url}/audio/speech"

        api_key = self.config.get("qwen_api_key", "")
        model = self.config.get("qwen_model", "cosyvoice-v2")

        speed = self._parse_rate(rate)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        with open(output_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                f.write(chunk)
                        return True

                    elif resp.status == 429:
                        # Rate-limited — exponential back-off
                        wait = min(2 ** attempt, 16)
                        await asyncio.sleep(wait)
                        continue

                    elif resp.status == 401:
                        raise PermissionError(
                            "Invalid API key. Check your Qwen/DashScope credentials."
                        )

                    else:
                        body = await resp.text()
                        raise RuntimeError(
                            f"API error {resp.status}: {body[:300]}"
                        )

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == max_retries - 1:
                    raise RuntimeError(
                        f"Request failed after {max_retries} retries: {exc}"
                    )
                await asyncio.sleep(2 ** attempt)

        return False

    @staticmethod
    def _parse_rate(rate_str: str) -> float:
        """Convert Edge-style rate string (e.g. '+20%') to speed multiplier."""
        try:
            val = int(rate_str.replace("%", "").replace("+", "").replace("-", ""))
            if "-" in rate_str and val != 0:
                val = -val
            return max(0.25, min(4.0, 1.0 + val / 100.0))
        except (ValueError, TypeError):
            return 1.0

    # ── Voice listing ───────────────────────────────────────────

    async def list_voices(self) -> List[VoiceInfo]:
        """Return preset voices. In future, can query an API endpoint."""
        return self.VOICE_PRESETS.copy()

    # ── Validation ──────────────────────────────────────────────

    def validate_config(self) -> List[str]:
        errors = []
        if not self.config.get("qwen_api_key"):
            errors.append("API key is required for Qwen3 OmniVoice.")
        if not self.config.get("qwen_model"):
            errors.append("A model name must be specified.")
        return errors

    # ── Lifecycle ───────────────────────────────────────────────

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None