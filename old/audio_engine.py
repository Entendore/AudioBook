import asyncio
import os
import subprocess
import tempfile
import shutil
import heapq
import time
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QThread, Signal

from text_processor import TextProcessor
from tts_backends import create_backend
from tts_backends.base import TTSBackend


@dataclass(order=True)
class ChunkResult:
    index: int
    filepath: str = field(compare=False)


class AudioEngine(QThread):
    # ── Signals ─────────────────────────────────────────────────
    progress = Signal(int, str)       # (percent, status_text)
    log = Signal(str)                 # HTML-capable log lines
    finished = Signal(bool, str)      # (success, message)

    def __init__(
        self,
        source: str,
        output_path: str,
        config: dict,
        is_raw_text: bool = False,
    ):
        super().__init__()
        self.source = source
        self.output_path = output_path
        self.config = config
        self.is_raw_text = is_raw_text

        # TTS Backend
        self.backend: TTSBackend = create_backend(
            config["backend"], config
        )

        # Concurrency
        self.concurrency = config.get("concurrency", 15)
        self.chunk_size = config.get("chunk_size", 500)
        self.out_format = config.get("output_format", "mp3")
        self.normalize = config.get("normalize_audio", True)

        # State
        self.is_cancelled = False
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=self.concurrency * 2)
        self.heap: list = []
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_chunks = 0
        self.temp_dir = tempfile.mkdtemp(prefix="audiobook_")
        self._start_time = 0.0

        # Backend-specific voice/param keys
        bid = config["backend"]
        if bid == "qwen_omnivoice":
            self.voice = config.get("qwen_voice", "Serena")
            self.rate = "+0%"
            self.volume = "+0%"
            self.pitch = "+0Hz"
        else:
            self.voice = config.get("edge_voice", "en-US-AvaNeural")
            self.rate = config.get("edge_rate", "+0%")
            self.volume = config.get("edge_volume", "+0%")
            self.pitch = config.get("edge_pitch", "+0Hz")

    # ── Producer ────────────────────────────────────────────────

    async def producer(self):
        try:
            idx = 0
            for chunk in TextProcessor.chunk_generator(
                self.source, self.chunk_size, self.is_raw_text
            ):
                if self.is_cancelled:
                    break
                if not chunk:
                    continue

                await self.queue.put((idx, chunk))
                self.total_tasks = idx + 1

                if idx % 25 == 0:
                    self.log.emit(f"📄 Read chunk {idx + 1}…")
                idx += 1

            self.log.emit(
                f"<b>Text processing complete — {idx} chunks queued.</b>"
            )
        except Exception as e:
            self.log.emit(f'<font color="red">Producer error: {e}</font>')
        finally:
            for _ in range(self.concurrency):
                await self.queue.put(None)

    # ── Consumer ────────────────────────────────────────────────

    async def consumer(self, worker_id: int):
        while True:
            if self.is_cancelled:
                break

            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if item is None:
                self.queue.task_done()
                break

            idx, text = item
            temp_path = os.path.join(self.temp_dir, f"chunk_{idx:06d}.mp3")

            try:
                await self._synthesize_with_retry(text, temp_path)

                heapq.heappush(self.heap, ChunkResult(index=idx, filepath=temp_path))

                self.completed_tasks += 1
                pct = int(10 + (self.completed_tasks / max(1, self.total_tasks)) * 75)
                elapsed = time.time() - self._start_time
                eta = self._estimate_eta(elapsed)
                self.progress.emit(
                    pct,
                    f"Generated {self.completed_tasks}/{self.total_tasks}  •  ETA {eta}",
                )

            except Exception as e:
                self.failed_chunks += 1
                self.log.emit(
                    f'<font color="red">✗ Chunk {idx} failed: {str(e)[:80]}</font>'
                )
            finally:
                self.queue.task_done()

    async def _synthesize_with_retry(self, text: str, output_path: str):
        """Retry synthesis up to 3 times with back-off."""
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                ok = await self.backend.synthesize(
                    text, output_path,
                    voice=self.voice,
                    rate=self.rate,
                    volume=self.volume,
                    pitch=self.pitch,
                )
                if ok:
                    return
                raise RuntimeError("Backend returned False")
            except Exception as exc:
                if attempt == max_attempts:
                    raise
                wait = 2 ** attempt
                self.log.emit(
                    f'<font color="orange">⚠ Retry {attempt}/{max_attempts} '
                    f'after {wait}s… ({exc})</font>'
                )
                await asyncio.sleep(wait)

    def _estimate_eta(self, elapsed: float) -> str:
        if self.completed_tasks < 2:
            return "calculating…"
        rate = self.completed_tasks / elapsed
        remaining = (self.total_tasks - self.completed_tasks) / rate
        mins, secs = divmod(int(remaining), 60)
        return f"{mins}m {secs}s" if mins else f"{secs}s"

    # ── Assembly ────────────────────────────────────────────────

    async def run_async(self):
        self._start_time = time.time()
        self.progress.emit(2, "Initializing pipeline…")

        # Validate backend
        errors = self.backend.validate_config()
        if errors:
            raise ValueError("Backend config errors:\n" + "\n".join(errors))

        self.progress.emit(5, "Starting parallel generation…")

        consumers = [
            asyncio.create_task(self.consumer(i))
            for i in range(self.concurrency)
        ]
        producer_task = asyncio.create_task(self.producer())

        await producer_task
        await asyncio.gather(*consumers)

        if self.is_cancelled:
            raise RuntimeError("Cancelled by user.")

        # ── Build concat list ────────────────────────────────────
        self.progress.emit(88, "Assembling audio…")

        if not self.heap:
            raise RuntimeError("No audio chunks were generated successfully.")

        concat_list = os.path.join(self.temp_dir, "concat_list.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            while self.heap:
                item = heapq.heappop(self.heap)
                safe = item.filepath.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        mp3_file = f"{self.output_path}.mp3"
        wav_file = f"{self.output_path}.wav"
        result_files = []

        # ── Concatenate MP3 ──────────────────────────────────────
        raw_mp3 = f"{self.output_path}_raw.mp3"

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", raw_mp3,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {proc.stderr[:300]}")

        # ── Loudness normalization (optional) ─────────────────────
        if self.normalize:
            self.progress.emit(92, "Normalizing loudness (EBU R128)…")
            self._normalize_audio(raw_mp3, mp3_file)
            try:
                os.remove(raw_mp3)
            except OSError:
                pass
        else:
            shutil.move(raw_mp3, mp3_file)

        result_files.append(mp3_file)

        # ── WAV conversion (if requested) ─────────────────────────
        if self.out_format in ("wav", "both"):
            self.progress.emit(95, "Encoding WAV…")
            cmd = [
                "ffmpeg", "-y", "-i", mp3_file,
                "-acodec", "pcm_s16le", "-ar", "44100", wav_file,
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            result_files.append(wav_file)

        # ── Summary ───────────────────────────────────────────────
        elapsed_total = time.time() - self._start_time
        mins, secs = divmod(int(elapsed_total), 60)

        summary = (
            f"<b>✓ Audiobook produced in {mins}m {secs}s</b><br>"
            f"Chunks: {self.completed_tasks} generated"
        )
        if self.failed_chunks:
            summary += f", <font color='orange'>{self.failed_chunks} failed</font>"
        summary += "<br>"
        for fp in result_files:
            size_mb = os.path.getsize(fp) / (1024 * 1024)
            summary += f"📄 {os.path.basename(fp)} ({size_mb:.1f} MB)<br>"

        return result_files, summary

    def _normalize_audio(self, input_path: str, output_path: str):
        """Two-pass EBU R128 loudness normalization targeting -16 LUFS (audiobook standard)."""
        # Pass 1 — measure
        cmd_analyze = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        proc = subprocess.run(cmd_analyze, capture_output=True, text=True)
        stats = self._parse_loudnorm_stats(proc.stderr)

        if not stats:
            # Fallback: single-pass
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                "-ar", "44100", output_path,
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            return

        # Pass 2 — apply with measured values
        cmd_apply = [
            "ffmpeg", "-y", "-i", input_path,
            "-af",
            (
                f"loudnorm=I=-16:TP=-1.5:LRA=11"
                f":measured_I={stats['input_i']}"
                f":measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}"
                f":measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}"
                f":linear=true"
            ),
            "-ar", "44100", output_path,
        ]
        subprocess.run(cmd_apply, capture_output=True, text=True, check=True)

    @staticmethod
    def _parse_loudnorm_stats(stderr: str) -> dict:
        """Extract loudnorm JSON stats from FFmpeg stderr."""
        import json as _json
        lines = stderr.splitlines()
        capturing = False
        json_lines = []
        for line in lines:
            if "{" in line:
                capturing = True
            if capturing:
                json_lines.append(line)
            if "}" in line and capturing:
                break
        if not json_lines:
            return {}
        try:
            return _json.loads("\n".join(json_lines))
        except _json.JSONDecodeError:
            return {}

    # ── Thread entry ────────────────────────────────────────────

    def run(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            files, summary = loop.run_until_complete(self.run_async())
            self.progress.emit(100, "Complete!")
            self.finished.emit(True, summary)

        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            try:
                loop.run_until_complete(self.backend.close())
            except Exception:
                pass
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass
            if loop and not loop.is_closed():
                loop.close()

    def cancel(self):
        self.is_cancelled = True
        self.log.emit('<font color="orange">Cancelling…</font>')