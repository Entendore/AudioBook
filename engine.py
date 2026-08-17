"""
Thin QThread wrapper around :class:`AudiobookPipeline`.

All business logic lives in ``pipeline.py``; this module only
bridges async callbacks → Qt signals.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from config import EngineConfig
from tts_backends import TTSBackend
from pipeline import AudiobookPipeline, PipelineResult, PipelineCancelled

logger = logging.getLogger(__name__)


class AudiobookEngine(QThread):
    """QThread that runs the audiobook pipeline and emits Qt signals."""

    progress = Signal(int, str)
    log = Signal(str)
    chapter_progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(
        self,
        source: str,
        output_path: str,
        config: EngineConfig,
        backend: TTSBackend,
        is_raw_text: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.source = source
        self.output_path = output_path
        self.is_raw_text = is_raw_text

        self._backend = backend
        self._pipeline = AudiobookPipeline(
            config=config,
            backend=backend,
            on_progress=self._on_progress,
            on_log=self._log,
            on_chapter=self._on_chapter,
        )

    # ── Slots for pipeline callbacks (thread-safe via Signal) ───

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.emit(pct, msg)

    def _log(self, msg: str) -> None:
        self.log.emit(msg)

    def _on_chapter(self, current: int, total: int) -> None:
        self.chapter_progress.emit(current, total)

    # ── Cancellation ────────────────────────────────────────────

    def cancel(self) -> None:
        self._pipeline.cancel()
        self.log.emit('<font color="orange">Cancelling…</font>')

    # ── Thread entry ────────────────────────────────────────────

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result: PipelineResult = loop.run_until_complete(
                self._pipeline.run(self.source, self.output_path, self.is_raw_text)
            )
            self.progress.emit(100, "Complete!")
            self.finished.emit(True, result.summary_html)

        except PipelineCancelled:
            self.finished.emit(False, "Cancelled by user.")

        except Exception as exc:
            logger.exception("Pipeline failed")
            self.finished.emit(False, str(exc))

        finally:
            try:
                loop.run_until_complete(self._backend.close())
            except Exception:
                pass
            loop.close()