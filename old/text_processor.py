import os
import re
from typing import Generator, List, Tuple, Optional

# ── Optional dependency guards ──────────────────────────────────
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


@dataclass_eq
class Chapter:
    """Represents a detected chapter."""
    index: int
    title: str
    text: str


class TextProcessor:
    """Streaming text extraction, cleaning, and intelligent chunking."""

    CHAPTER_RE = re.compile(
        r"^(?i)(chapter\s+\d+|part\s+\d+|section\s+\d+|"
        r"prologue|epilogue|introduction|preface|conclusion)\b",
        re.MULTILINE,
    )

    # ── Public API ──────────────────────────────────────────────

    @staticmethod
    def detect_chapters(source: str, is_raw_text: bool = False) -> List[Chapter]:
        """Detect chapters in the source text. Returns list of Chapter objects."""
        full_text = TextProcessor._get_full_text(source, is_raw_text)
        if not full_text.strip():
            return []

        splits = TextProcessor.CHAPTER_RE.split(full_text)

        # If no chapter markers found, return single chapter
        if len(splits) <= 1:
            return [Chapter(index=0, title="Full Text", text=full_text.strip())]

        chapters = []
        i = 0
        idx = 0
        while i < len(splits):
            chunk = splits[i].strip()
            if not chunk:
                i += 1
                continue

            # Check if this chunk is a chapter title
            if TextProcessor.CHAPTER_RE.match(chunk):
                title = chunk.strip()
                body = splits[i + 1].strip() if i + 1 < len(splits) else ""
                chapters.append(Chapter(index=idx, title=title, text=body))
                idx += 1
                i += 2
            else:
                # Text before first chapter marker
                chapters.insert(0, Chapter(index=0, title="Introduction", text=chunk))
                # Re-index
                for c in chapters:
                    c.index = chapters.index(c)
                idx = len(chapters)
                i += 1

        return chapters if chapters else [Chapter(index=0, title="Full Text", text=full_text.strip())]

    @staticmethod
    def chunk_generator(
        source: str,
        max_chars: int = 500,
        is_raw_text: bool = False,
    ) -> Generator[str, None, None]:
        """
        State-machine sentence chunker that streams chunks respecting
        sentence boundaries within max_chars limits.
        """
        sentence_endings = re.compile(r'(?<=[.!?。！？])\s+')
        buffer = ""

        if is_raw_text:
            raw_stream = TextProcessor._read_raw_text(source)
        else:
            raw_stream = TextProcessor._read_raw_file(source)

        clean_stream = TextProcessor._clean_stream(raw_stream)

        for clean_chunk in clean_stream:
            buffer += clean_chunk

            while len(buffer) > max_chars:
                match = sentence_endings.search(buffer, 0, max_chars + 80)
                if match:
                    cut = match.end()
                    piece = buffer[:cut].strip()
                    if piece:
                        yield piece
                    buffer = buffer[cut:].strip()
                else:
                    piece = buffer[:max_chars].strip()
                    if piece:
                        yield piece
                    buffer = buffer[max_chars:].strip()

        remainder = buffer.strip()
        if remainder:
            yield remainder

    # ── Internal helpers ────────────────────────────────────────

    @staticmethod
    def _get_full_text(source: str, is_raw_text: bool) -> str:
        """Get the full text as a single string for chapter detection."""
        parts = []
        if is_raw_text:
            for block in TextProcessor._read_raw_text(source):
                parts.append(block)
        else:
            for block in TextProcessor._read_raw_file(source):
                parts.append(block)
        return "".join(parts)

    @staticmethod
    def _clean_stream(text_stream: Generator) -> Generator[str, None, None]:
        for chunk in text_stream:
            # Remove URLs and emails
            chunk = re.sub(r'https?://\S+|www\.\S+|[\w\.-]+@[\w\.-]+', '', chunk)
            # Rejoin hyphenated line breaks
            chunk = re.sub(r'-\s*\n\s*', '', chunk)
            # Normalize whitespace
            chunk = re.sub(r'\s+', ' ', chunk)
            if chunk.strip():
                yield chunk

    @staticmethod
    def _read_raw_file(filepath: str) -> Generator[str, None, None]:
        ext = os.path.splitext(filepath)[1].lower()

        if ext == '.txt':
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                while True:
                    block = f.read(65536)
                    if not block:
                        break
                    yield block

        elif ext == '.pdf':
            if not PDF_OK:
                raise ImportError("Install pypdf: pip install pypdf")
            reader = PdfReader(filepath)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    yield text + "\n"

        elif ext == '.docx':
            if not DOCX_OK:
                raise ImportError("Install python-docx: pip install python-docx")
            doc = Document(filepath)
            for para in doc.paragraphs:
                if para.text.strip():
                    yield para.text + "\n"

        elif ext in ('.md', '.html', '.htm'):
            if not BS4_OK:
                raise ImportError("Install beautifulsoup4: pip install beautifulsoup4")
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            if ext != '.md':
                soup = BeautifulSoup(content, 'html.parser')
                for tag in soup(["script", "style"]):
                    tag.decompose()
                yield soup.get_text(separator="\n")
            else:
                yield content

        elif ext == '.epub':
            if not EPUB_OK:
                raise ImportError("Install EbookLib: pip install ebooklib")
            if not BS4_OK:
                raise ImportError("Install beautifulsoup4: pip install beautifulsoup4")
            book = epub.read_epub(filepath)
            for item in book.get_items():
                if item.get_type() == 9:  # ITEM_DOCUMENT
                    try:
                        soup = BeautifulSoup(item.get_content(), 'html.parser')
                        for tag in soup(["script", "style"]):
                            tag.decompose()
                        text = soup.get_text(separator='\n')
                        if text.strip():
                            yield text + "\n"
                    except Exception:
                        continue
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    @staticmethod
    def _read_raw_text(raw_text: str) -> Generator[str, None, None]:
        block_size = 8192
        for i in range(0, len(raw_text), block_size):
            yield raw_text[i : i + block_size]


# Fix missing import for dataclass
from dataclasses import dataclass

@dataclass
class Chapter:
    index: int
    title: str
    text: str