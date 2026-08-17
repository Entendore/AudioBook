"""
Streaming text extraction, cleaning, chapter detection, and chunking.
Includes Context-Aware NLP-based speaker detection for multi-voice audiobooks.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, List, Tuple

# ── Optional dependencies (Document Parsing) ────────────────────
try:
    from pypdf import PdfReader
    PDF_OK = True
except ImportError:
    PDF_OK = False

try:
    from docx import Document
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

try:
    from ebooklib import epub
    EPUB_OK = True
except ImportError:
    EPUB_OK = False

# ── Optional NLP Dependency (spaCy) ─────────────────────────────
try:
    import spacy
    NLP = spacy.load("en_core_web_sm")
    SPACY_OK = True
except Exception:
    NLP = None
    SPACY_OK = False


@dataclass(frozen=True, slots=True)
class Chapter:
    """An immutable chapter detected in source text."""
    index: int
    title: str
    text: str
    word_count: int = 0

    def __post_init__(self):
        if self.word_count == 0 and self.text:
            object.__setattr__(self, "word_count", len(self.text.split()))


@dataclass(frozen=True, slots=True)
class TextStats:
    """Summary statistics for a text source."""
    char_count: int
    word_count: int
    estimated_minutes: float
    chapter_count: int
    speakers_detected: int

    @property
    def estimated_str(self) -> str:
        m = int(self.estimated_minutes)
        if m < 1:
            return "<1 min"
        h, r = divmod(m, 60)
        return f"{h}h {r}m" if h else f"{m}m"


@dataclass(frozen=True, slots=True)
class DialogueChunk:
    """
    A chunk of text containing one or more segments.
    Designed for SSML multi-voice synthesis.
    """
    text: str                                     # Full combined text (for fallback backends)
    dominant_speaker: str                         # The speaker with the most text in this chunk
    segments: Tuple[Tuple[str, str], ...]         # ((text, speaker), (text, speaker), ...)


WPM_ESTIMATE = 155.0

CHAPTER_RE = re.compile(
    r"^(chapter\s+\d+|part\s+\d+|section\s+\d+|"
    r"prologue|epilogue|introduction|preface|conclusion)\b",
    re.MULTILINE | re.IGNORECASE,
)

SPEECH_VERBS = {
    'said', 'says', 'asked', 'asks', 'replied', 'replies', 'whispered', 
    'shouted', 'muttered', 'exclaimed', 'cried', 'thought', 'snapped', 
    'laughed', 'agreed', 'sighed', 'growled', 'hissed', 'yelled', 
    'screamed', 'demanded', 'offered', 'stated', 'declared', 'continued', 
    'added', 'observed', 'remarked', 'wondered', 'called', 'interrupted',
    'insisted', 'urged', 'begged', 'pleaded', 'grumbled', 'mumbled'
}

PRONOUNS_AND_STOPWORDS = {
    "I", "You", "He", "She", "It", "We", "They", "Me", "Him", "Her", 
    "Us", "Them", "My", "Your", "His", "Its", "Our", "Their",
    "The", "A", "An", "And", "But", "Or", "So", "If", "Then", "Than",
    "When", "While", "As", "Because", "Since", "Until", "Although",
    "Chapter", "Part", "Section", "Book", "Volume", "Prologue", "Epilogue",
    "There", "Here", "What", "Who", "How", "Why", "No", "Yes", "Not"
}

_VERB_GROUP = "|".join(SPEECH_VERBS)
TAG_RE = re.compile(
    rf'([A-Z][a-zA-Z]+)\s+(?:{_VERB_GROUP})(?:ed|s|ing)?\b'
    rf'|\b(?:{_VERB_GROUP})(?:ed|s|ing)?\s+([A-Z][a-zA-Z]+)',
    re.IGNORECASE
)


class TextProcessor:
    """Stateless text processing — all methods are static / class methods."""

    @staticmethod
    def compute_stats(
        source: str,
        is_raw_text: bool = False,
    ) -> TextStats:
        full = TextProcessor._collect_text(source, is_raw_text)
        chars = len(full)
        words = len(full.split()) if full else 0
        est_min = words / WPM_ESTIMATE if words else 0
        chapters = TextProcessor.detect_chapters(source, is_raw_text)
        speakers = TextProcessor.extract_speakers(source, is_raw_text)
            
        return TextStats(
            char_count=chars,
            word_count=words,
            estimated_minutes=est_min,
            chapter_count=len(chapters),
            speakers_detected=len(speakers),
        )

    @staticmethod
    def extract_speakers(
        source: str, is_raw_text: bool = False
    ) -> List[str]:
        full = TextProcessor._collect_text(source, is_raw_text)
        if not full.strip():
            return []

        speakers = set()
        if SPACY_OK:
            chunk_size = 500000
            for i in range(0, len(full), chunk_size):
                doc = NLP(full[i:i+chunk_size])
                for token in doc:
                    if token.lemma_.lower() in SPEECH_VERBS:
                        for child in token.children:
                            if child.dep_ in ("nsubj", "nsubjpass", "agent", "attr", "csubj"):
                                if child.ent_type_ in ("PERSON", "ORG") or child.pos_ in ("PROPN",):
                                    if child.text not in PRONOUNS_AND_STOPWORDS:
                                        speakers.add(child.text)
        else:
            for match in TAG_RE.finditer(full):
                name = match.group(1) or match.group(2)
                if name and name not in PRONOUNS_AND_STOPWORDS:
                    speakers.add(name)
        return sorted(list(speakers))

    @staticmethod
    def detect_chapters(source: str, is_raw_text: bool = False) -> List[Chapter]:
        full = TextProcessor._collect_text(source, is_raw_text)
        if not full.strip():
            return []

        splits = CHAPTER_RE.split(full)
        if len(splits) <= 1:
            return [Chapter(index=0, title="Full Text", text=full.strip())]

        chapters: List[Chapter] = []
        i = 0
        idx = 0
        while i < len(splits):
            chunk = splits[i].strip()
            if not chunk:
                i += 1
                continue
            if CHAPTER_RE.match(chunk):
                title = chunk.strip()
                body = splits[i + 1].strip() if i + 1 < len(splits) else ""
                chapters.append(Chapter(index=idx, title=title, text=body))
                idx += 1
                i += 2
            else:
                chapters.insert(0, Chapter(index=0, title="Introduction", text=chunk))
                for ci, c in enumerate(chapters):
                    object.__setattr__(c, "index", ci)
                idx = len(chapters)
                i += 1
        return chapters or [Chapter(index=0, title="Full Text", text=full.strip())]

    # ── Chunking ────────────────────────────────────────────────

    @staticmethod
    def chunk_generator(
        source: str,
        max_chars: int = 500,
        is_raw_text: bool = False,
        multi_speaker: bool = False,
    ) -> Generator[DialogueChunk, None, None]:
        """Yields DialogueChunk objects containing text and speaker segments."""
        full = TextProcessor._collect_text(source, is_raw_text)
        
        if not multi_speaker:
            sentence_end = re.compile(r'(?<=[.!?。！？])\s+')
            buffer = ""
            for clean in TextProcessor._clean_stream([full]):
                buffer += clean
                while len(buffer) > max_chars:
                    m = sentence_end.search(buffer, 0, max_chars + 80)
                    if m:
                        piece = buffer[:m.end()].strip()
                        if piece: 
                            yield DialogueChunk(piece, "Narrator", ((piece, "Narrator"),))
                        buffer = buffer[m.end():].strip()
                    else:
                        piece = buffer[:max_chars].strip()
                        if piece: 
                            yield DialogueChunk(piece, "Narrator", ((piece, "Narrator"),))
                        buffer = buffer[max_chars:].strip()
            if buffer.strip():
                yield DialogueChunk(buffer.strip(), "Narrator", ((buffer.strip(), "Narrator"),))
        else:
            yield from TextProcessor._stream_speaker_chunks(full, max_chars)

    # ── Advanced Context-Aware NLP Dialogue Parsing ─────────────

    @staticmethod
    def _stream_speaker_chunks(
        text: str, max_chars: int
    ) -> Generator[DialogueChunk, None, None]:
        """
        Groups sentences into DialogueChunks. 
        Keeps multi-speaker dialogue together up to max_chars for seamless SSML synthesis.
        """
        sentence_end = re.compile(r'(?<=[.!?])\s+')
        sentences = sentence_end.split(text)
        
        buffer_segments: List[Tuple[str, str]] = []
        buffer_len = 0
        current_speaker = "Narrator"
        last_actor = "Narrator"
        
        for sent in sentences:
            if not sent.strip(): continue
            
            speaker, is_action_beat = TextProcessor._determine_speaker(
                sent, current_speaker, last_actor
            )
            
            if is_action_beat and speaker != "Narrator":
                last_actor = speaker
            elif speaker not in ("Narrator", "Dialogue"):
                last_actor = speaker
                
            # Yield chunk if adding this sentence exceeds max_chars
            if buffer_segments and (buffer_len + len(sent) > max_chars):
                full_text = " ".join([s for s, _ in buffer_segments])
                # Determine dominant speaker for fallback backends
                speaker_counts = {}
                for _, spk in buffer_segments:
                    speaker_counts[spk] = speaker_counts.get(spk, 0) + 1
                dominant = max(speaker_counts, key=speaker_counts.get)
                
                yield DialogueChunk(full_text, dominant, tuple(buffer_segments))
                buffer_segments = []
                buffer_len = 0
                
            buffer_segments.append((sent, speaker))
            buffer_len += len(sent)
            current_speaker = speaker
            
        if buffer_segments:
            full_text = " ".join([s for s, _ in buffer_segments])
            speaker_counts = {}
            for _, spk in buffer_segments:
                speaker_counts[spk] = speaker_counts.get(spk, 0) + 1
            dominant = max(speaker_counts, key=speaker_counts.get)
            yield DialogueChunk(full_text, dominant, tuple(buffer_segments))

    @staticmethod
    def _determine_speaker(
        sentence: str, last_speaker: str, last_actor: str
    ) -> Tuple[str, bool]:
        has_quote = bool(re.search(r'["\u201c\u201d\u2018\u2019—]', sentence))
        
        if SPACY_OK:
            speaker = TextProcessor._spacy_extract_speaker(sentence)
        else:
            speaker = TextProcessor._regex_extract_speaker(sentence)
            
        if speaker:
            return speaker, False
            
        if not has_quote:
            if SPACY_OK:
                actor = TextProcessor._spacy_extract_actor(sentence)
                if actor: return actor, True
            else:
                actor = TextProcessor._regex_extract_actor(sentence)
                if actor: return actor, True

        if has_quote:
            if last_actor and last_actor != "Narrator":
                return last_actor, False
            return last_speaker if last_speaker != "Narrator" else "Dialogue", False
            
        return "Narrator", False

    @staticmethod
    def _spacy_extract_speaker(sentence: str) -> str | None:
        doc = NLP(sentence)
        for token in doc:
            if token.lemma_.lower() in SPEECH_VERBS:
                for child in token.children:
                    if child.dep_ in ("nsubj", "nsubjpass", "agent", "attr", "csubj"):
                        if child.ent_type_ in ("PERSON", "ORG") or child.pos_ in ("PROPN",):
                            if child.text not in PRONOUNS_AND_STOPWORDS:
                                return child.text
        return None

    @staticmethod
    def _spacy_extract_actor(sentence: str) -> str | None:
        doc = NLP(sentence)
        for token in doc:
            if token.pos_ == "VERB" and token.lemma_.lower() not in SPEECH_VERBS:
                for child in token.children:
                    if child.dep_ in ("nsubj", "nsubjpass", "agent", "csubj"):
                        if child.ent_type_ in ("PERSON", "ORG") or child.pos_ in ("PROPN",):
                            if child.text not in PRONOUNS_AND_STOPWORDS:
                                return child.text
        return None

    @staticmethod
    def _regex_extract_speaker(sentence: str) -> str | None:
        match = TAG_RE.search(sentence)
        if match:
            name = match.group(1) or match.group(2)
            if name and name not in PRONOUNS_AND_STOPWORDS:
                return name
        return None

    @staticmethod
    def _regex_extract_actor(sentence: str) -> str | None:
        match = re.match(r'^([A-Z][a-zA-Z]+)\s+(?:\w+\s+)?(?:walked|nodded|turned|slammed|smiled|stood|sat|grabbed|took|ran|looked|stared|sighed)\b', sentence)
        if match:
            name = match.group(1)
            if name not in PRONOUNS_AND_STOPWORDS:
                return name
        return None

    # ── Internals ───────────────────────────────────────────────

    @staticmethod
    def _collect_text(source: str, is_raw_text: bool) -> str:
        stream = (
            TextProcessor._stream_raw_text(source)
            if is_raw_text
            else TextProcessor._stream_raw_file(source)
        )
        return "".join(stream)

    @staticmethod
    def _clean_stream(text_stream) -> Generator[str, None, None]:
        url_re = re.compile(r'https?://\S+|www\.\S+|[\w\.-]+@[\w\.-]+')
        for chunk in text_stream:
            chunk = url_re.sub('', chunk)
            chunk = re.sub(r'-\s*\n\s*', '', chunk)
            chunk = re.sub(r'\s+', ' ', chunk)
            if chunk.strip():
                yield chunk

    @staticmethod
    def _stream_raw_file(filepath: str) -> Generator[str, None, None]:
        ext = Path(filepath).suffix.lower()
        if ext == '.txt':
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                while block := f.read(65536): yield block
        elif ext == '.pdf':
            if not PDF_OK: raise ImportError("pip install pypdf")
            for page in PdfReader(filepath).pages:
                if text := page.extract_text(): yield text + "\n"
        elif ext == '.docx':
            if not DOCX_OK: raise ImportError("pip install python-docx")
            for para in Document(filepath).paragraphs:
                if para.text.strip(): yield para.text + "\n"
        elif ext in ('.md', '.html', '.htm'):
            if not BS4_OK: raise ImportError("pip install beautifulsoup4")
            content = Path(filepath).read_text(encoding='utf-8', errors='replace')
            if ext != '.md':
                soup = BeautifulSoup(content, 'html.parser')
                for tag in soup(["script", "style"]): tag.decompose()
                yield soup.get_text(separator="\n")
            else: yield content
        elif ext == '.epub':
            if not EPUB_OK: raise ImportError("pip install ebooklib")
            if not BS4_OK: raise ImportError("pip install beautifulsoup4")
            book = epub.read_epub(filepath)
            for item in book.get_items():
                if item.get_type() == 9:
                    try:
                        soup = BeautifulSoup(item.get_content(), 'html.parser')
                        for tag in soup(["script", "style"]): tag.decompose()
                        if text := soup.get_text(separator='\n').strip(): yield text + "\n"
                    except Exception: continue
        else: raise ValueError(f"Unsupported format: {ext}")

    @staticmethod
    def _stream_raw_text(raw: str) -> Generator[str, None, None]:
        bs = 8192
        for i in range(0, len(raw), bs):
            yield raw[i:i + bs]