"""
FFmpeg-based audio post-processing for broadcast-quality audiobooks.

Features: two-pass EBU R128 normalisation, silence trimming, micro-fade,
M4B chapter assembly, cover art embedding, duration measurement.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_LUFS = -16.0
DEFAULT_TP = -1.0


@dataclass(frozen=True, slots=True)
class ChapterMarker:
    """Chapter boundary for M4B metadata."""
    title: str
    start_ms: int
    end_ms: int


@dataclass
class ProcessingResult:
    """Result of the post-processing pipeline."""
    files: List[Path] = field(default_factory=list)
    total_duration_ms: float = 0.0
    warnings: List[str] = field(default_factory=list)

    def add_file(self, p: Path) -> None:
        if p.exists():
            self.files.append(p)


class AudioPostProcessor:
    """Configurable, instance-based audio post-processor."""

    def __init__(
        self,
        target_lufs: float = DEFAULT_LUFS,
        true_peak: float = DEFAULT_TP,
        inter_chunk_silence: float = 0.25,
        silence_threshold_db: int = -35,
        fade_duration: float = 0.015,
    ):
        self.target_lufs = target_lufs
        self.true_peak = true_peak
        self.inter_chunk_silence = inter_chunk_silence
        self.silence_threshold_db = silence_threshold_db
        self.fade_duration = fade_duration

    # ── Public pipeline ─────────────────────────────────────────

    def process(
        self,
        chunk_paths: List[Path],
        output_path: str,
        output_format: str = "mp3",
        normalize: bool = True,
        trim_silence: bool = True,
        chapters: Optional[List[ChapterMarker]] = None,
        title: str = "Audiobook",
        author: str = "Unknown",
        cover_art: str = "",
    ) -> ProcessingResult:
        """Run the full pipeline: concat → trim → normalize → encode."""
        result = ProcessingResult()

        # 1. Concatenate
        raw = Path(f"{output_path}_raw.mp3")
        if not self.concatenate(chunk_paths, raw):
            result.warnings.append("Concatenation failed")
            return result

        current = raw

        # 2. Trim silence
        if trim_silence:
            trimmed = Path(f"{output_path}_trimmed.mp3")
            self.trim_silence_file(current, trimmed)
            if trimmed.exists():
                current = trimmed

        # 3. Normalize loudness
        if normalize:
            normed = Path(f"{output_path}_norm.mp3")
            self.normalize_loudness(current, normed)
            if normed.exists():
                current = normed

        # 4. Final MP3
        mp3 = Path(f"{output_path}.mp3")
        current.replace(mp3)
        result.add_file(mp3)

        # 5. Duration
        result.total_duration_ms = self.get_duration_ms(mp3)

        # 6. WAV
        if output_format in ("wav", "both", "all"):
            wav = Path(f"{output_path}.wav")
            self._run_ffmpeg([
                "ffmpeg", "-y", "-i", str(mp3),
                "-acodec", "pcm_s16le", "-ar", "44100", str(wav),
            ])
            result.add_file(wav)

        # 7. M4B with chapters + cover
        if output_format in ("m4b", "all") and chapters:
            m4b = Path(f"{output_path}.m4b")
            if self.create_m4b(mp3, chapters, m4b, title, author, cover_art):
                result.add_file(m4b)

        # 8. Embed cover art in MP3 (if not making M4B)
        elif cover_art and output_format not in ("m4b",) and Path(cover_art).exists():
            tagged = Path(f"{output_path}_tagged.mp3")
            self._embed_cover_mp3(mp3, Path(cover_art), tagged, title, author)
            if tagged.exists():
                tagged.replace(mp3)

        # Cleanup intermediates
        for p in (raw,):
            if p.exists() and p not in result.files:
                p.unlink(missing_ok=True)

        return result

    # ── Loudness ────────────────────────────────────────────────

    def measure_loudness(self, input_path: Path) -> Optional[dict]:
        cmd = [
            "ffmpeg", "-hide_banner", "-i", str(input_path),
            "-af", f"loudnorm=I={self.target_lufs}:TP={self.true_peak}:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        m = re.search(r"\{[\s\S]*\"input_i\"[\s\S]*\}", r.stderr)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None

    def normalize_loudness(self, input_path: Path, output_path: Path) -> bool:
        stats = self.measure_loudness(input_path)
        if stats is None:
            logger.warning("Loudness measurement failed — copying as-is")
            self._run_ffmpeg(["ffmpeg", "-y", "-i", str(input_path), "-c", "copy", str(output_path)])
            return output_path.exists()

        af = (
            f"loudnorm=I={self.target_lufs}:TP={self.true_peak}:LRA=11"
            f":measured_I={stats.get('input_i', self.target_lufs)}"
            f":measured_TP={stats.get('input_tp', self.true_peak)}"
            f":measured_LRA={stats.get('input_lra', '11.0')}"
            f":measured_thresh={stats.get('input_thresh', '-70.0')}"
            f":offset={stats.get('target_offset', '0.0')}:linear=true"
        )
        return self._run_ffmpeg([
            "ffmpeg", "-y", "-hide_banner", "-i", str(input_path),
            "-af", af, "-ar", "44100",
            "-codec:a", "libmp3lame", "-b:a", "192k", str(output_path),
        ])

    # ── Silence Trim ────────────────────────────────────────────

    def trim_silence_file(self, input_path: Path, output_path: Path) -> bool:
        db = self.silence_threshold_db
        af = (
            f"silenceremove=start_periods=1:start_silence=0.1:start_threshold={db}dB,"
            f"apad=whole_dur=0.15,atrim=start=0.15,areverse,"
            f"silenceremove=start_periods=1:start_silence=0.1:start_threshold={db}dB,"
            f"areverse"
        )
        ok = self._run_ffmpeg([
            "ffmpeg", "-y", "-hide_banner", "-i", str(input_path),
            "-af", af, "-ar", "44100", str(output_path),
        ])
        if not ok:
            logger.warning("Trim failed — copying original")
            self._run_ffmpeg(["ffmpeg", "-y", "-i", str(input_path), "-c", "copy", str(output_path)])
        return output_path.exists()

    # ── Concatenation ───────────────────────────────────────────

    def concatenate(self, chunk_paths: List[Path], output_path: Path) -> bool:
        with tempfile.TemporaryDirectory() as td:
            concat_file = Path(td) / "concat.txt"
            silence = Path(td) / "silence.mp3"

            # Generate inter-chunk silence
            self._run_ffmpeg([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                "-t", str(self.inter_chunk_silence),
                "-codec:a", "libmp3lame", "-b:a", "192k", str(silence),
            ])

            lines: List[str] = []
            for i, p in enumerate(chunk_paths):
                lines.append(f"file '{_bash_safe(p)}'")
                if i < len(chunk_paths) - 1 and silence.exists():
                    lines.append(f"file '{_bash_safe(silence)}'")

            concat_file.write_text("\n".join(lines), encoding="utf-8")

            return self._run_ffmpeg([
                "ffmpeg", "-y", "-hide_banner",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file), "-c", "copy", str(output_path),
            ])

    # ── M4B ─────────────────────────────────────────────────────

    def create_m4b(
        self,
        mp3_input: Path,
        chapters: List[ChapterMarker],
        output_path: Path,
        title: str = "Audiobook",
        author: str = "Unknown",
        cover_art: str = "",
    ) -> bool:
        with tempfile.TemporaryDirectory() as td:
            meta = Path(td) / "metadata.txt"
            lines = [";FFMETADATA1", f"title={title}", f"artist={author}", ""]
            for ch in chapters:
                lines += [
                    "[CHAPTER]", "TIMEBASE=1/1000",
                    f"START={ch.start_ms}", f"END={ch.end_ms}",
                    f"title={ch.title}", "",
                ]
            meta.write_text("\n".join(lines), encoding="utf-8")

            cmd = [
                "ffmpeg", "-y", "-hide_banner",
                "-i", str(mp3_input), "-i", str(meta),
                "-map_metadata", "1",
                "-codec:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
            ]
            if cover_art and Path(cover_art).exists():
                cmd += ["-i", cover_art, "-map", "2:v", "-c:v", "mjpeg"]
            cmd.append(str(output_path))

            return self._run_ffmpeg(cmd)

    # ── Cover Art for MP3 ───────────────────────────────────────

    def _embed_cover_mp3(
        self, mp3: Path, cover: Path, output: Path, title: str, author: str,
    ) -> bool:
        return self._run_ffmpeg([
            "ffmpeg", "-y", "-i", str(mp3), "-i", str(cover),
            "-map", "0:a", "-map", "1:v",
            "-c:a", "copy", "-c:v", "mjpeg",
            "-metadata", f"title={title}", "-metadata", f"artist={author}",
            str(output),
        ])

    # ── Duration ────────────────────────────────────────────────

    @staticmethod
    def get_duration_ms(filepath: Path) -> float:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(filepath)],
            capture_output=True, text=True,
        )
        try:
            return float(r.stdout.strip()) * 1000.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def format_duration(ms: float) -> str:
        s = int(ms / 1000)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}h {m}m {sec}s" if h else f"{m}m {sec}s"

    # ── Chapter Markers from chapter audio files ────────────────

    @staticmethod
    def build_chapter_markers(
        chapter_paths: List[Path],
        chapter_titles: List[str],
    ) -> List[ChapterMarker]:
        markers: List[ChapterMarker] = []
        offset = 0
        for path, title in zip(chapter_paths, chapter_titles):
            dur = AudioPostProcessor.get_duration_ms(path)
            markers.append(ChapterMarker(
                title=title, start_ms=int(offset), end_ms=int(offset + dur),
            ))
            offset += dur
        return markers

    # ── Internal ────────────────────────────────────────────────

    @staticmethod
    def _run_ffmpeg(cmd: List[str]) -> bool:
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            logger.error("FFmpeg error: %s", r.stderr.decode()[:300])
        return r.returncode == 0


def _bash_safe(p: Path) -> str:
    """Escape a path for FFmpeg concat list."""
    return str(p).replace("\\", "/").replace("'", "'\\''")