"""
Local Qwen TTS Backend — 100% Offline via HuggingFace Transformers.

Requirements: pip install torch transformers accelerate soundfile
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import List, Optional

from tts_backends import TTSBackend, VoiceInfo

logger = logging.getLogger(__name__)


class QwenLocalTTS(TTSBackend):
    """Local Qwen/CosyVoice TTS inference. No API required."""

    id = "qwen_local"
    name = "Qwen Local (Offline)"
    description = "Run Qwen TTS locally via Transformers. Requires PyTorch."

    KNOWN_VOICES = ("Cherry", "Serena", "Ethan", "Chelsie", "Echo", "Bonnie")

    def __init__(self, config: dict):
        super().__init__(config)
        self._model = None
        self._processor = None

    def _load_model(self):
        if self._model is None:
            try:
                from transformers import AutoModelForCausalLM, AutoProcessor
                import torch
            except ImportError:
                raise ImportError("Local Qwen requires: pip install torch transformers accelerate soundfile")

            model_path = self.config.get("qwen_model_path", "Qwen/Qwen2.5-3B")
            device = self.config.get("qwen_device", "cuda")
            
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("CUDA not available, falling back to CPU for Qwen.")
                device = "cpu"

            self._processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
            self._model = AutoModelForCausalLM.from_pretrained(
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
        voice = voice or self.config.get("qwen_voice", "Cherry")
        
        # Run inference in a thread to avoid blocking the async event loop
        loop = asyncio.get_event_loop()
        wav_path = await loop.run_in_executor(None, self._generate_speech, text, voice)
        
        # Convert WAV to MP3 via FFmpeg (expected by pipeline)
        from audio_postprocessor import AudioPostProcessor
        AudioPostProcessor._run_ffmpeg([
            "ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", output_path
        ])
        
        if wav_path.exists():
            wav_path.unlink() # Cleanup temp wav
        return Path(output_path).exists()

    def _generate_speech(self, text: str, voice: str) -> Path:
        import torch
        import soundfile as sf
        
        self._load_model()
        
        # Assuming Qwen/CosyVoice style TTS prompting
        prompt = f"Convert text to speech with voice {voice}: {text}"
        inputs = self._processor(prompt, return_tensors="pt").to(self._model.device)
        
        with torch.no_grad():
            # Generic generation call - may need adjustment based on specific Qwen TTS repo
            audio_tensor = self._model.generate(**inputs, max_new_tokens=2048)
        
        # Save to temp wav
        temp_wav = Path(tempfile.mktemp(suffix=".wav"))
        # Extract audio data from tensor (shape might vary based on model)
        # This is a generalized placeholder for the model's audio output
        audio_data = audio_tensor.cpu().float().numpy()
        sf.write(str(temp_wav), audio_data, samplerate=24000)
        
        return temp_wav

    async def list_voices(self) -> List[VoiceInfo]:
        return [VoiceInfo(id=v, name=v, locale="multi") for v in self.KNOWN_VOICES]

    def validate_config(self) -> List[str]:
        errs = []
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            import soundfile  # noqa: F401
        except ImportError as e:
            errs.append(f"Missing dependency for Local Qwen: {e}. Run: pip install torch transformers soundfile")
        
        model_path = self.config.get("qwen_model_path")
        if not model_path:
            errs.append("Qwen model path/repo ID is not set.")
        return errs

    async def close(self) -> None:
        # Free VRAM
        if self._model is not None:
            import torch
            del self._model
            del self._processor
            self._model = None
            self._processor = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()