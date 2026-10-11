"""
Pure-async audiobook generation pipeline — no Qt dependency.
"""

from __future__ import annotations

import asyncio
import random
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from config import EngineConfig
from text_processor import TextProcessor, Chapter, DialogueChunk
from tts_backends import TTSBackend
from audio_postprocessor import AudioPostProcessor, ChapterMarker, ProcessingResult


class PipelineError(Exception): pass
class ConfigurationError(PipelineError): pass
class PipelineCancelled(PipelineError): pass
class SynthesisError(PipelineError): pass


@dataclass(frozen=True, slots=True)
class PipelineResult:
    output_files: Tuple[Path, ...]
    total_duration_ms: float
    total_chunks: int
    failed_chunks: int
    elapsed_seconds: float
    chapter_count: int

    @property
    def success(self) -> bool: return len(self.output_files) > 0

    @property
    def duration_str(self) -> str: return AudioPostProcessor.format_duration(self.total_duration_ms)

    @property
    def elapsed_str(self) -> str:
        m, s = divmod(int(self.elapsed_seconds), 60)
        return f"{m}m {s}s"

    @property
    def summary_html(self) -> str:
        parts = [f"<b>✓ Audiobook produced in {self.elapsed_str}</b><br>"]
        if self.chapter_count > 1: parts.append(f"Chapters: {self.chapter_count} • ")
        parts.append(f"Chunks: {self.total_chunks}")
        if self.failed_chunks: parts.append(f", <font color='orange'>{self.failed_chunks} failed</font>")
        parts.append(f"<br>Duration: {self.duration_str}<br>")
        for fp in self.output_files:
            try:
                mb = fp.stat().st_size / (1024 * 1024)
                ext = fp.suffix.upper().lstrip(".")
                parts.append(f"📄 {fp.name} ({ext}, {mb:.1f} MB)<br>")
            except OSError: pass
        return "".join(parts)


@contextmanager
def temp_dir(prefix: str = "audiobook_"):
    d = Path(tempfile.mkdtemp(prefix=prefix))
    try: yield d
    finally: shutil.rmtree(d, ignore_errors=True)


async def retry_async(
    coro_fn: Callable[..., asyncio.coroutines], *args,
    max_attempts: int = 3, base_delay: float = 4.0,
    on_retry: Optional[Callable[[int, str], None]] = None, **kwargs,
) -> bool:
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = await coro_fn(*args, **kwargs)
            if result is False: raise RuntimeError("Backend returned False")
            return True
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1.0)
                if on_retry: on_retry(attempt, str(exc)[:80])
                await asyncio.sleep(delay)
    raise SynthesisError(str(last_exc))


class AudiobookPipeline:
    def __init__(
        self, config: EngineConfig, backend: TTSBackend,
        on_progress: Optional[Callable[[int, str], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_chapter: Optional[Callable[[int, int], None]] = None,
    ):
        self.cfg = config
        self.backend = backend
        self._progress = on_progress or (lambda p, m: None)
        self._log = on_log or (lambda m: None)
        self._chapter_cb = on_chapter or (lambda c, t: None)
        self._cancel = asyncio.Event()
        self._start = 0.0
        self._completed = 0
        self._total = 0
        self._failed = 0

    def cancel(self) -> None: self._cancel.set()

    def _check_cancel(self) -> None:
        if self._cancel.is_set(): raise PipelineCancelled("Cancelled by user")

    def _eta(self) -> str:
        if self._completed < 2: return "calculating…"
        elapsed = time.monotonic() - self._start
        rate = self._completed / elapsed
        remaining = (self._total - self._completed) / max(rate, 0.001)
        m, s = divmod(int(remaining), 60)
        return f"{m}m {s}s" if m else f"{s}s"

    def _resolve_voice(self, speaker: str) -> str:
        """Map detected speaker to configured voice, falling back to defaults."""
        if speaker in self.cfg.voice_map:
            return self.cfg.voice_map[speaker]
        if "Narrator" in self.cfg.voice_map and speaker != "Dialogue":
            return self.cfg.voice_map["Narrator"]
        if "Dialogue" in self.cfg.voice_map:
            return self.cfg.voice_map["Dialogue"]
        return self.cfg.voice

    async def run(self, source: str, output_path: str, is_raw_text: bool) -> PipelineResult:
        self._start = time.monotonic()
        self._completed = 0
        self._failed = 0
        self._progress(1, "Validating…")
        errs = self.backend.validate_config()
        if errs: raise ConfigurationError("\n".join(errs))
        self._check_cancel()

        if self.cfg.chapter_aware:
            return await self._run_chapter_mode(source, output_path, is_raw_text)
        return await self._run_flat_mode(source, output_path, is_raw_text)

    async def _run_flat_mode(self, source: str, output_path: str, is_raw_text: bool) -> PipelineResult:
        self._progress(3, "Chunking text…")
        chunks = list(TextProcessor.chunk_generator(
            source, self.cfg.chunk_size, is_raw_text, self.cfg.multi_speaker
        ))
        self._total = len(chunks)
        self._log(f"<b>{self._total} chunks queued</b>")

        with temp_dir() as td:
            self._progress(5, "Synthesizing…")
            chunk_map = await self._synthesize_all(chunks, td)
            self._check_cancel()
            self._progress(85, "Post-processing…")

            ordered = [chunk_map[i] for i in sorted(chunk_map)]
            processor = AudioPostProcessor()
            pp = processor.process(
                chunk_paths=ordered, output_path=output_path,
                output_format=self.cfg.output_format, normalize=self.cfg.normalize,
                trim_silence=self.cfg.trim_silence, title=self.cfg.title,
                author=self.cfg.author, cover_art=self.cfg.cover_art,
            )
        return self._build_result(pp, 0)

    async def _run_chapter_mode(self, source: str, output_path: str, is_raw_text: bool) -> PipelineResult:
        self._progress(2, "Detecting chapters…")
        chapters = TextProcessor.detect_chapters(source, is_raw_text)
        n_ch = len(chapters)
        self._log(f"<b>📖 Detected {n_ch} chapter(s)</b>")

        chapter_audios: List[Path] = []
        chapter_titles: List[str] = []
        total_chunks = 0

        with temp_dir(prefix="audiobook_ch_") as td:
            for ci, chapter in enumerate(chapters):
                self._check_cancel()
                self._chapter_cb(ci + 1, n_ch)
                self._log(f"🎙️ Chapter {ci + 1}/{n_ch}: <b>{chapter.title}</b>")

                ch_chunks = list(TextProcessor.chunk_generator(
                    chapter.text, self.cfg.chunk_size, is_raw_text=True, 
                    multi_speaker=self.cfg.multi_speaker
                ))
                if not ch_chunks:
                    self._log(f'<font color="orange">⚠️ Empty chapter: {chapter.title}</font>')
                    continue

                ch_dir = td / f"ch_{ci:03d}"
                ch_dir.mkdir()
                base_pct = 5 + int((ci / n_ch) * 75)
                
                chunk_map = await self._synthesize_all(ch_chunks, ch_dir, base_pct=base_pct)
                self._check_cancel()

                ordered = [chunk_map[i] for i in sorted(chunk_map)]
                ch_audio = ch_dir / "chapter.mp3"
                processor = AudioPostProcessor()
                if not processor.concatenate(ordered, ch_audio):
                    self._log(f'<font color="red">Concat failed: ch {ci + 1}</font>')
                    continue

                chapter_audios.append(ch_audio)
                chapter_titles.append(chapter.title)
                total_chunks += len(ch_chunks)

            self._check_cancel()
            self._progress(82, "Post-processing…")
            markers = AudioPostProcessor.build_chapter_markers(chapter_audios, chapter_titles)
            
            processor = AudioPostProcessor()
            pp = processor.process(
                chunk_paths=chapter_audios, output_path=output_path,
                output_format=self.cfg.output_format, normalize=self.cfg.normalize,
                trim_silence=self.cfg.trim_silence, chapters=markers,
                title=self.cfg.title, author=self.cfg.author, cover_art=self.cfg.cover_art,
            )
        self._total = total_chunks
        return self._build_result(pp, n_ch)

    async def _synthesize_all(
        self, chunks: List[DialogueChunk], output_dir: Path, base_pct: int = 5
    ) -> Dict[int, Path]:
        sem = asyncio.Semaphore(self.cfg.concurrency)
        results: Dict[int, Path] = {}
        lock = asyncio.Lock()
        self._completed = 0
        self._total = len(chunks)

        async def _worker(idx: int, chunk: DialogueChunk) -> None:
            if self._cancel.is_set(): return
            async with sem:
                if self._cancel.is_set(): return
                out = output_dir / f"chunk_{idx:06d}.mp3"

                # Map chunk segments to voices
                segments = [(text, self._resolve_voice(speaker)) for text, speaker in chunk.segments]

                def _on_retry(attempt: int, msg: str) -> None:
                    self._log(f'<font color="orange">⚠ Retry {attempt}/3: {msg}</font>')

                try:
                    await retry_async(
                        self.backend.synthesize_segments, segments, str(out),
                        rate=self.cfg.rate, volume=self.cfg.volume, pitch=self.cfg.pitch,
                        on_retry=_on_retry,
                    )
                    async with lock:
                        results[idx] = out
                        self._completed += 1
                        pct = base_pct + int((self._completed / max(1, self._total)) * 30)
                        self._progress(pct, f"Generated {self._completed}/{self._total}  •  ETA {self._eta()}")
                except SynthesisError as exc:
                    async with lock: self._failed += 1
                    self._log(f'<font color="red">✗ Chunk {idx}: {exc}</font>')

        tasks = [asyncio.create_task(_worker(i, chunk)) for i, chunk in enumerate(chunks)]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    def _build_result(self, pp: ProcessingResult, chapter_count: int) -> PipelineResult:
        elapsed = time.monotonic() - self._start
        return PipelineResult(
            output_files=tuple(pp.files), total_duration_ms=pp.total_duration_ms,
            total_chunks=self._completed, failed_chunks=self._failed,
            elapsed_seconds=elapsed, chapter_count=chapter_count,
        )