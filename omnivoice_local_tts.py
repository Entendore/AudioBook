"""
Local OmniVoice TTS Backend — 100% Offline via HuggingFace Transformers.

Requirements: pip install torch transformers accelerate soundfile
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import List

from tts_backends import TTSBackend, VoiceInfo

logger = logging.getLogger(__name__)


class OmniVoiceLocalTTS(TTSBackend):
    """Local OmniVoice TTS inference. No API required."""

    id = "omnivoice_local"
    name = "OmniVoice Local (Offline)"
    description = "Run OmniVoice locally via Transformers. Requires PyTorch."

    def __init__(self, config: dict):
        super().__init__(config)
        self._model = None
        self._processor = None

    def _load_model(self):
        if self._model is None:
            try:
                from transformers import AutoModelForTextToSpectrogram, AutoProcessor
                import torch
            except ImportError:
                raise ImportError("Local OmniVoice requires: pip install torch transformers accelerate soundfile")

            model_path = self.config.get("omnivoice_model_path", "OmniVoice/OmniVoice-TTS")
            device = self.config.get("omnivoice_device", "cuda")
            
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU for OmniVoice.")
                device = "cpu"

            self._processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
            self._model = AutoModelForTextToSpectrogram.from_pretrained(
                model_path, 
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map=device,
                trust_remote_code=True
            )
            self._model.eval()

    async def synthesize(
        self, text: str, output_path: str, voice: str = "",
        rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz",
    ) -> bool:
        speaker_id = int(voice) if voice.isdigit() else self.config.get("omnivoice_speaker_id", 0)
        
        loop = asyncio.get_event_loop()
        wav_path = await loop.run_in_executor(None, self._generate_speech, text, speaker_id)
        
        from audio_postprocessor import AudioPostProcessor
        AudioPostProcessor._run_ffmpeg([
            "ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", output_path
        ])
        
        if wav_path.exists():
            wav_path.unlink()
        return Path(output_path).exists()

    def _generate_speech(self, text: str, speaker_id: int) -> Path:
        import torch
        import soundfile as sf
        
        self._load_model()
        
        inputs = self._processor(text, return_tensors="pt", speaker_id=speaker_id).to(self._model.device)
        
        with torch.no_grad():
            audio_tensor = self._model.generate(**inputs)
        
        temp_wav = Path(tempfile.mktemp(suffix=".wav"))
        audio_data = audio_tensor.cpu().float().numpy()
        sf.write(str(temp_wav), audio_data, samplerate=24000)
        
        return temp_wav

    async def list_voices(self) -> List[VoiceInfo]:
        # For multi-speaker models, list some placeholder IDs
        return [VoiceInfo(id=str(i), name=f"Speaker {i}") for i in range(10)]

    def validate_config(self) -> List[str]:
        errs = []
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            import soundfile  # noqa: F401
        except ImportError as e:
            errs.append(f"Missing dependency for Local OmniVoice: {e}. Run: pip install torch transformers soundfile")
        
        model_path = self.config.get("omnivoice_model_path")
        if not model_path:
            errs.append("OmniVoice model path/repo ID is not set.")
        return errs

    async def close(self) -> None:
        if self._model is not None:
            import torch
            del self._model
            del self._processor
            self._model = None
            self._processor = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()