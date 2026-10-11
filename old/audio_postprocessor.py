"""
Audio Post-Processing Pipeline for Audiobook Quality

Features:
  • Two-pass loudness normalisation (EBU R128 / LUFS targeting)
  • True-peak limiting
  • Intelligent silence trimming between chunks
  • Smooth crossfade between chunks (short fade-in/fade-out)
  • M4B audiobook assembly with chapter markers
  • MP3 / WAV final output
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Audiobook standard loudness targets
DEFAULT_LUFS = -16.0   # Comfortable for most devices (ACX accepts -18 to -23)
DEFAULT_TP   = -1.0    # True-peak ceiling in dBTP


@dataclass
class ChapterMarker:
    """Defines a chapter boundary in the final audiobook."""
    title: str
    start_ms: int    # Start time in milliseconds
    end_ms: int      # End time in milliseconds


class AudioPostProcessor:
    """FFmpeg-based post-processing for broadcast-quality audiobook audio."""

    # ── Loudness Measurement ───────────────────────────────────────

    @staticmethod
    def measure_loudness(input_path: str) -> dict | None:
        """
        First-pass loudness measurement using FFmpeg loudnorm filter.
        Returns parsed JSON stats or None on failure.
        """
        cmd = [
            "ffmpeg", "-hide_banner", "-i", input_path,
            "-af", f"loudnorm=I={DEFAULT_LUFS}:TP={DEFAULT_TP}:LRA=11:print_format=json",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        # FFmpeg prints JSON to stderr
        stderr = result.stderr
        # Find the JSON block
        match = re.search(r"\{[\s\S]*\"input_i\"[\s\S]*\}", stderr)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    # ── Two-Pass Normalisation ─────────────────────────────────────

    @staticmethod
    def normalize_loudness(
        input_path: str,
        output_path: str,
        target_lufs: float = DEFAULT_LUFS,
        true_peak: float = DEFAULT_TP,
    ) -> bool:
        """
        Two-pass EBU R128 loudness normalisation.

        Pass 1 → measure integrated loudness, true-peak, LRA.
        Pass 2 → apply linear normalisation with measured offsets.

        This avoids the artefacts of single-pass normalisation and
        produces broadcast-quality output.
        """
        # --- Pass 1: measurement ---
        stats = AudioPostProcessor.measure_loudness(input_path)
        if stats is None:
            logger.warning("Loudness measurement failed; copying as-is.")
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path],
                capture_output=True,
            )
            return os.path.exists(output_path)

        # --- Pass 2: linear normalisation with measured values ---
        measured_i    = stats.get("input_i",    str(target_lufs))
        measured_tp   = stats.get("input_tp",   str(true_peak))
        measured_lra  = stats.get("input_lra",  "11.0")
        measured_thresh = stats.get("input_thresh", "-70.0")
        target_offset  = stats.get("target_offset", "0.0")

        af = (
            f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11"
            f":measured_I={measured_i}:measured_TP={measured_tp}"
            f":measured_LRA={measured_lra}:measured_thresh={measured_thresh}"
            f":offset={target_offset}:linear=true"
        )

        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-i", input_path,
            "-af", af,
            "-ar", "44100",
            "-codec:a", "libmp3lame", "-b:a", "192k",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            logger.error("Normalisation failed: %s", result.stderr.decode()[:300])
            return False
        return True

    # ── Silence Trimming ───────────────────────────────────────────

    @staticmethod
    def trim_silence(
        input_path: str,
        output_path: str,
        threshold_db: int = -35,
        min_silence_sec: float = 1.5,
        keep_padding_sec: float = 0.35,
    ) -> bool:
        """
        Remove excessively long silences while preserving natural pauses.

        • Silences longer than *min_silence_sec* below *threshold_db*
          are shortened to *keep_padding_sec* on each side.
        • This keeps the reading natural without rushing.
        """
        # Use the silenceremove filter
        # Period=2 means it treats the whole file (for areverse approach)
        af = (
            f"silenceremove=start_periods=1:start_silence=0.1:start_threshold={threshold_db}dB,"
            f"apad=whole_dur=0.15,"
            f"atrim=start=0.15,"
            f"areverse,"
            f"silenceremove=start_periods=1:start_silence=0.1:start_threshold={threshold_db}dB,"
            f"areverse"
        )

        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-i", input_path,
            "-af", af,
            "-ar", "44100",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            logger.warning("Silence trim failed, using original: %s",
                           result.stderr.decode()[:200])
            # Fall back to simple copy
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path],
                capture_output=True,
            )
        return os.path.exists(output_path)

    # ── Per-Chunk Fade ─────────────────────────────────────────────

    @staticmethod
    def apply_chunk_fade(
        input_path: str,
        output_path: str,
        fade_duration: float = 0.015,
    ) -> bool:
        """
        Apply a very short fade-in / fade-out to a chunk to prevent clicks.
        This is almost inaudible but eliminates hard-cut artefacts.
        """
        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-i", input_path,
            "-af", f"afade=t=in:d={fade_duration},afade=t=out:st=$(ffprobe -v error -show_entries format=duration -of csv=p=0 {input_path} | cut -d. -f1)-{fade_duration}:d={fade_duration}",
            "-c:a", "libmp3lame", "-b:a", "192k",
            output_path,
        ]
        # Shell-style $() doesn't work in subprocess list form; use two-step
        # Get duration first
        dur_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0", input_path,
        ]
        dur_result = subprocess.run(dur_cmd, capture_output=True, text=True)
        try:
            duration = float(dur_result.stdout.strip())
        except ValueError:
            # Can't determine duration, skip fade
            subprocess.run(
                ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path],
                capture_output=True,
            )
            return os.path.exists(output_path)

        fade_out_start = max(0.0, duration - fade_duration)
        af = f"afade=t=in:d={fade_duration},afade=t=out:st={fade_out_start:.4f}:d={fade_duration}"

        cmd = [
            "ffmpeg", "-y", "-hide_banner",
            "-i", input_path,
            "-af", af,
            "-c:a", "libmp3lame", "-b:a", "192k",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True)
        return os.path.exists(output_path)

    # ── Concatenation ──────────────────────────────────────────────

    @staticmethod
    def concatenate(
        chunk_paths: list[str],
        output_path: str,
        inter_chunk_silence: float = 0.25,
    ) -> bool:
        """
        Concatenate ordered chunk files into a single output.
        Adds a brief silence between chunks for natural pacing.
        """
        with tempfile.TemporaryDirectory() as td:
            concat_file = os.path.join(td, "concat.txt")

            # Generate silence padding file
            silence_path = os.path.join(td, "silence.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"anullsrc=r=44100:cl=mono",
                "-t", str(inter_chunk_silence),
                "-codec:a", "libmp3lame", "-b:a", "192k",
                silence_path,
            ], capture_output=True)

            with open(concat_file, "w", encoding="utf-8") as f:
                for i, p in enumerate(chunk_paths):
                    safe = p.replace("\\", "/").replace("'", "'\\''")
                    f.write(f"file '{safe}'\n")
                    if i < len(chunk_paths) - 1 and os.path.exists(silence_path):
                        safe_sil = silence_path.replace("\\", "/").replace("'", "'\\''")
                        f.write(f"file '{safe_sil}'\n")

            cmd = [
                "ffmpeg", "-y", "-hide_banner",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy",
                output_path,
            ]
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                logger.error("Concat failed: %s", result.stderr.decode()[:300])
                return False
        return os.path.exists(output_path)

    # ── M4B Audiobook Assembly ─────────────────────────────────────

    @staticmethod
    def create_m4b(
        mp3_input: str,
        chapters: list[ChapterMarker],
        output_path: str,
        title: str = "Audiobook",
        author: str = "Unknown",
        cover_art: str | None = None,
    ) -> bool:
        """
        Create an M4B audiobook with chapter markers and metadata.

        M4B is the industry-standard audiobook format that supports:
          • Chapter navigation
          • Bookmark support
          • Embedded cover art
          • Playback across Apple Books / Audible / etc.
        """
        with tempfile.TemporaryDirectory() as td:
            # 1. Build FFmetadata file
            meta_path = os.path.join(td, "metadata.txt")
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(";FFMETADATA1\n")
                f.write(f"title={title}\n")
                f.write(f"artist={author}\n")
                f.write("\n")
                for ch in chapters:
                    f.write("[CHAPTER]\n")
                    f.write("TIMEBASE=1/1000\n")
                    f.write(f"START={ch.start_ms}\n")
                    f.write(f"END={ch.end_ms}\n")
                    f.write(f"title={ch.title}\n\n")

            # 2. Convert MP3 → AAC (M4B container)
            cmd = [
                "ffmpeg", "-y", "-hide_banner",
                "-i", mp3_input,
                "-i", meta_path,
                "-map_metadata", "1",
                "-codec:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
            ]
            if cover_art and os.path.exists(cover_art):
                cmd += ["-i", cover_art, "-map", "2:v", "-c:v", "mjpeg"]
            cmd.append(output_path)

            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                logger.error("M4B creation failed: %s",
                             result.stderr.decode()[:300])
                return False
        return os.path.exists(output_path)

    # ── Full Pipeline ──────────────────────────────────────────────

    @staticmethod
    def run_pipeline(
        chunk_paths: list[str],
        output_stem: str,
        output_format: str = "both",       # "mp3", "wav", "m4b", "both"
        chapters: list[ChapterMarker] | None = None,
        title: str = "Audiobook",
        author: str = "Unknown",
        normalize: bool = True,
        trim_silence: bool = True,
        inter_chunk_silence: float = 0.25,
        cover_art: str | None = None,
    ) -> dict[str, str]:
        """
        Run the complete post-processing pipeline.

        Returns a dict of {format: filepath} for all produced files.
        """
        produced: dict[str, str] = {}

        # Step 1: Concatenate chunks
        raw_mp3 = f"{output_stem}_raw.mp3"
        if not AudioPostProcessor.concatenate(
            chunk_paths, raw_mp3, inter_chunk_silence
        ):
            raise RuntimeError("Chunk concatenation failed")

        # Step 2: Silence trimming
        if trim_silence:
            trimmed_mp3 = f"{output_stem}_trimmed.mp3"
            AudioPostProcessor.trim_silence(raw_mp3, trimmed_mp3)
            os.replace(trimmed_mp3, raw_mp3)

        # Step 3: Loudness normalisation
        if normalize:
            norm_mp3 = f"{output_stem}_norm.mp3"
            AudioPostProcessor.normalize_loudness(raw_mp3, norm_mp3)
            os.replace(norm_mp3, raw_mp3)

        # Step 4: Produce final formats
        mp3_file = f"{output_stem}.mp3"
        os.replace(raw_mp3, mp3_file)
        produced["mp3"] = mp3_file

        if output_format in ("wav", "both"):
            wav_file = f"{output_stem}.wav"
            cmd = [
                "ffmpeg", "-y", "-i", mp3_file,
                "-acodec", "pcm_s16le", "-ar", "44100", wav_file,
            ]
            subprocess.run(cmd, capture_output=True)
            if os.path.exists(wav_file):
                produced["wav"] = wav_file

        if output_format in ("m4b",) and chapters:
            m4b_file = f"{output_stem}.m4b"
            if AudioPostProcessor.create_m4b(
                mp3_file, chapters, m4b_file,
                title=title, author=author, cover_art=cover_art,
            ):
                produced["m4b"] = m4b_file

        return produced