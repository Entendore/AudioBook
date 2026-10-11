"""
Chapter-aware audiobook generation engine.

Extends the basic AudioEngine to:
  - Detect chapters from source text
  - Generate audio per-chapter with chapter boundaries
  - Pass chapter metadata to AudioPostProcessor for M4B/ID3 markers
  - Provide accurate per-chapter progress
"""

import asyncio
import os
import shutil
import tempfile
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

from text_processor import TextProcessor, Chapter
from audio_postprocessor import AudioPostProcessor, ProcessingResult
from tts_backends import create_backend
from tts_backends.base import TTSBackend


class ChapterEngine(QThread):
    """
    Production-grade audiobook engine with chapter awareness.

    Pipeline:
      1. Detect chapters in source
      2. For each chapter → chunk text → synthesize chunks → concat chapter
      3. Post-process: normalize, trim silence
      4. Assemble final audiobook with chapter metadata
    """

    progress = Signal(int, str)
    log = Signal(str)
    chapter_progress = Signal(int, int)   # (current_chapter, total_chapters)
    finished = Signal(bool, str)

    def __init__(
        self,
        source: str,
        output_path: str,
        config: dict,
        is_raw_text: bool = False,
        enable_ssml: bool = False,
        trim_silence: bool = True,
    ):
        super().__init__()
        self.source = source
        self.output_path = output_path
        self.config = config
        self.is_raw_text = is_raw_text
        self.enable_ssml = enable_ssml
        self.trim_silence = trim_silence

        self.backend: TTSBackend = create_backend(config["backend"], config)
        self.concurrency = config.get("concurrency", 15)
        self.chunk_size = config.get("chunk_size", 500)
        self.out_format = config.get("output_format", "mp3")
        self.normalize = config.get("normalize_audio", True)

        # Voice config
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

        self.is_cancelled = False
        self._start_time = 0.0
        self.temp_dir = tempfile.mkdtemp(prefix="audiobook_ch_")

    # ── Chapter Detection ───────────────────────────────────────

    def _detect_chapters(self) -> List[Chapter]:
        """Detect chapters and log results."""
        chapters = TextProcessor.detect_chapters(self.source, self.is_raw_text)
        self.log.emit(f"<b>📖 Detected {len(chapters)} chapter(s)</b>")
        for ch in chapters[:10]:  # Show first 10
            preview = ch.text[:60].replace("\n", " ")
            self.log.emit(f"   {ch.index + 1}. {ch.title} — <i>{preview}…</i>")
        if len(chapters) > 10:
            self.log.emit(f"   … and {len(chapters) - 10} more.")
        return chapters

    # ── Per-Chapter Synthesis ───────────────────────────────────

    async def _synthesize_chapter(
        self,
        chapter: Chapter,
        chapter_idx: int,
        total_chapters: int,
    ) -> Optional[str]:
        """
        Generate audio for a single chapter.
        Returns the path to the concatenated chapter audio file,
        or None on failure.
        """
        if self.is_cancelled:
            return None

        self.chapter_progress.emit(chapter_idx + 1, total_chapters)
        self.log.emit(
            f"🎙️ Chapter {chapter_idx + 1}/{total_chapters}: "
            f"<b>{chapter.title}</b>"
        )

        # Chunk the chapter text
        chunks = list(
            TextProcessor.chunk_generator(
                chapter.text, self.chunk_size, is_raw_text=True
            )
        )
        if not chunks:
            self.log.emit(
                f'<font color="orange">⚠️ Chapter "{chapter.title}" is empty — skipping.</font>'
            )
            return None

        chapter_dir = os.path.join(self.temp_dir, f"ch_{chapter_idx:03d}")
        os.makedirs(chapter_dir, exist_ok=True)

        # Synthesize chunks in parallel
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.concurrency * 2)
        results: dict = {}  # index -> filepath
        failed = 0

        # Fill queue
        for i, chunk_text in enumerate(chunks):
            await queue.put((i, chunk_text))
        for _ in range(self.concurrency):
            await queue.put(None)  # Sentinels

        async def worker(wid: int):
            nonlocal failed
            while True:
                if self.is_cancelled:
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if item is None:
                    queue.task_done()
                    break

                idx, text = item
                out = os.path.join(chapter_dir, f"chunk_{idx:04d}.mp3")
                try:
                    await self._synth_with_retry(text, out)
                    results[idx] = out
                except Exception as e:
                    failed += 1
                    self.log.emit(
                        f'<font color="red">✗ Ch{chapter_idx+1} chunk {idx}: {str(e)[:60]}</font>'
                    )
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker(i)) for i in range(self.concurrency)]
        await asyncio.gather(*workers)

        if self.is_cancelled:
            return None

        # Concatenate chapter chunks in order
        concat_list = os.path.join(chapter_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for i in sorted(results.keys()):
                safe = results[i].replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        chapter_audio = os.path.join(chapter_dir, "chapter.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list, "-c", "copy", chapter_audio,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)

        if proc.returncode != 0 or not os.path.exists(chapter_audio):
            self.log.emit(
                f'<font color="red">Concat failed for chapter {chapter_idx+1}</font>'
            )
            return None

        # Report progress
        overall_pct = int(5 + ((chapter_idx + 1) / total_chapters) * 75)
        self.progress.emit(overall_pct, f"Chapter {chapter_idx+1}/{total_chapters} done")

        if failed > 0:
            self.log.emit(
                f'<font color="orange">⚠️ Chapter {chapter_idx+1}: '
                f'{failed} chunk(s) failed</font>'
            )

        return chapter_audio

    async def _synth_with_retry(self, text: str, output_path: str):
        """Synthesize with exponential back-off retry."""
        for attempt in range(1, 4):
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
                if attempt == 3:
                    raise
                await asyncio.sleep(2 ** attempt)

    # ── Main Pipeline ───────────────────────────────────────────

    async def run_pipeline(self):
        import subprocess  # ensure available

        self._start_time = time.time()
        self.progress.emit(1, "Detecting chapters…")

        # Validate
        errors = self.backend.validate_config()
        if errors:
            raise ValueError("Backend config errors:\n" + "\n".join(errors))

        # Detect chapters
        chapters = self._detect_chapters()
        if not chapters:
            raise ValueError("No text content found.")

        total_chapters = len(chapters)
        self.log.emit(f"<b>Starting production: {total_chapters} chapters</b>")

        # Synthesize each chapter
        chapter_files: List[Tuple[int, str, str]] = []  # (idx, title, filepath)

        for i, chapter in enumerate(chapters):
            if self.is_cancelled:
                raise RuntimeError("Cancelled by user.")

            audio_path = await self._synthesize_chapter(chapter, i, total_chapters)
            if audio_path:
                chapter_files.append((i, chapter.title, audio_path))

        if not chapter_files:
            raise RuntimeError("No chapters were generated successfully.")

        # ── Post-Processing ──────────────────────────────────────
        self.progress.emit(82, "Post-processing…")

        # Build final concat list
        final_concat = os.path.join(self.temp_dir, "final_concat.txt")
        with open(final_concat, "w", encoding="utf-8") as f:
            for _, _, audio_path in chapter_files:
                safe = audio_path.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe}'\n")

        chapter_titles = [title for _, title, _ in chapter_files]

        # Run post-processor
        processor = AudioPostProcessor(log_fn=lambda s: self.log.emit(s))
        result = processor.process(
            concat_list_path=final_concat,
            output_path=self.output_path,
            output_format=self.out_format,
            normalize=self.normalize,
            trim_silence=self.trim_silence,
            chapter_titles=chapter_titles,
        )

        if result.errors:
            self.log.emit(
                f'<font color="orange">⚠️ Post-processing warnings: '
                f'{"; ".join(result.errors)}</font>'
            )

        # ── Summary ──────────────────────────────────────────────
        elapsed = time.time() - self._start_time
        mins, secs = divmod(int(elapsed), 60)

        summary = (
            f"<b>✓ Audiobook produced in {mins}m {secs}s</b><br>"
            f"Chapters: {len(chapter_files)}/{total_chapters} • "
            f"Duration: {AudioPostProcessor._format_duration(result.total_duration_ms)}<br>"
        )
        for fp in result.files:
            size_mb = os.path.getsize(fp) / (1024 * 1024)
            ext = os.path.splitext(fp)[1].upper().lstrip(".")
            summary += f"📄 {os.path.basename(fp)} ({ext}, {size_mb:.1f} MB)<br>"

        return result, summary

    # ── Thread Entry ────────────────────────────────────────────

    def run(self):
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            result, summary = loop.run_until_complete(self.run_pipeline())
            self.progress.emit(100, "Complete!")
            self.finished.emit(True, summary)

        except Exception as e:
            self.finished.emit(False, str(e))
        finally:
            try:
                if loop:
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


# Fix: ensure subprocess is imported in the module scope
import subprocess