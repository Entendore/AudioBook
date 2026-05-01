import os
import re

# --- Dependency Checks ---
try:
    from pypdf import PdfReader
    PDF_SUPPORT = True
except ImportError: PDF_SUPPORT = False

try:
    from docx import Document
    DOCX_SUPPORT = True
except ImportError: DOCX_SUPPORT = False

try:
    from bs4 import BeautifulSoup
    HTML_MD_SUPPORT = True
except ImportError: HTML_MD_SUPPORT = False

# NEW: Check for EPUB support
try:
    import ebooklib
    from ebooklib import epub
    EPUB_SUPPORT = True
except ImportError: EPUB_SUPPORT = False

class TextProcessor:
    @staticmethod
    def _clean_stream(text_stream):
        """
        Generator that yields cleaned chunks of text.
        """
        for chunk in text_stream:
            # Basic cleaning for each chunk
            chunk = re.sub(r'https?://\S+|www\.\S+|[\w\.-]+@[\w\.-]+', '', chunk)
            chunk = re.sub(r'-\s*\n\s*', '', chunk)
            chunk = re.sub(r'\s+', ' ', chunk)      
            if chunk.strip():
                yield chunk

    @staticmethod
    def _read_raw_file(filepath):
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.txt':
            with open(filepath, 'r', encoding='utf-8') as f:
                while True:
                    block = f.read(65536) # Read 64KB blocks
                    if not block: break
                    yield block
        elif ext == '.pdf':
            if not PDF_SUPPORT: raise ImportError("pypdf missing")
            reader = PdfReader(filepath)
            for page in reader.pages:
                text = page.extract_text()
                if text: yield text + "\n"
        elif ext == '.docx':
            if not DOCX_SUPPORT: raise ImportError("python-docx missing")
            doc = Document(filepath)
            for para in doc.paragraphs:
                yield para.text + "\n"
        elif ext in ['.md', '.html', '.htm']:
            if not HTML_MD_SUPPORT: raise ImportError("beautifulsoup4 missing")
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                if ext != '.md':
                    soup = BeautifulSoup(content, 'html.parser')
                    for script in soup(["script", "style"]): script.decompose()
                    yield soup.get_text(separator="\n")
                else:
                    yield content
        # NEW: EPUB Support
        elif ext == '.epub':
            if not EPUB_SUPPORT: raise ImportError("EbookLib missing")
            if not HTML_MD_SUPPORT: raise ImportError("beautifulsoup4 missing (needed for EPUB)")
            
            book = epub.read_epub(filepath)
            # Iterate through items in the book
            for item in book.get_items():
                # Type 9 is ITEM_DOCUMENT in ebooklib
                if item.get_type() == 9: 
                    try:
                        # EPUB content is usually HTML
                        soup = BeautifulSoup(item.get_content(), 'html.parser')
                        # Remove scripts/styles if any
                        for script in soup(["script", "style"]): script.decompose()
                        text = soup.get_text(separator='\n')
                        if text.strip():
                            yield text + "\n"
                    except Exception as e:
                        # Skip unreadable items
                        continue
        else:
            raise ValueError(f"Unsupported format: {ext}")

    @staticmethod
    def _read_raw_text(raw_text):
        """
        OPTIMIZATION: 
        Yields the raw text in manageable blocks (e.g., 5000 chars).
        This prevents the O(N^2) performance issue where string slicing 
        on a massive string freezes the application.
        """
        block_size = 5000
        for i in range(0, len(raw_text), block_size):
            yield raw_text[i:i+block_size]

    @staticmethod
    def chunk_generator(source, max_chars=500, is_raw_text=False):
        """
        State-Machine Sentence Chunker.
        Now efficient for both files and large pasted text.
        """
        sentence_endings = re.compile(r'(?<=[.!?])\s+')
        buffer = ""
        
        # Select source stream
        if is_raw_text:
            # Now uses the block-based reader for raw text
            raw_stream = TextProcessor._read_raw_text(source)
        else:
            raw_stream = TextProcessor._read_raw_file(source)
            
        clean_stream = TextProcessor._clean_stream(raw_stream)
        
        for clean_chunk in clean_stream:
            buffer += clean_chunk
            
            # Drain the buffer as much as possible
            while len(buffer) > max_chars:
                # Search for a sentence boundary to split at
                match = sentence_endings.search(buffer, 0, max_chars + 50)
                
                if match:
                    cut_point = match.end()
                    yield buffer[:cut_point].strip()
                    buffer = buffer[cut_point:].strip()
                else:
                    # No sentence ending found, force split (rare)
                    yield buffer[:max_chars].strip()
                    buffer = buffer[max_chars:].strip()
        
        # Yield remaining text
        if buffer.strip():
            yield buffer.strip()
