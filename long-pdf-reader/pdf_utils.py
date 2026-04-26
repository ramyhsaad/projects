"""
pdf_utils.py
------------
Pure helper functions for the long-pdf-reader app.

Kept free of Streamlit imports so the logic is unit-testable and a failure
in any helper cannot corrupt UI session state. The Streamlit layer in
app.py is responsible for catching exceptions raised here and rendering
user-friendly messages.

External services: only OpenAI, called via the official Python SDK.
"""
from __future__ import annotations

import io
import math
import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Models + tunables (kept conservative for cost and reliability)
# ---------------------------------------------------------------------------

DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"

CHUNK_TARGET_WORDS = 700
CHUNK_OVERLAP_WORDS = 80
EMBED_BATCH_SIZE = 64

# Heuristic: if the average extractable characters per page is below this,
# assume the PDF is scanned/image-only.
SCANNED_PDF_AVG_CHAR_THRESHOLD = 100

# Hard usage limits surfaced in the UI as well — keep in sync with app.py.
MAX_UPLOAD_MB = 50
MAX_SUMMARY_PAGES = 60
MAX_AUDIO_PAGES = 12
MAX_AUDIO_CLIPS_PER_RUN = 6
MAX_RETRIEVED_CHUNKS = 12
MAX_SUMMARY_CHUNKS = 40

# Retry policy for transient OpenAI failures
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.5  # seconds


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DocPage:
    """One extracted page. Text may be empty for image/blank pages."""
    page_number: int
    text: str


@dataclass
class TextChunk:
    """A chunk of text with provenance back to the source pages."""
    chunk_id: int
    page_start: int
    page_end: int
    text: str
    embedding: Optional[List[float]] = field(default=None, repr=False)


@dataclass
class ExtractionResult:
    """Result of pulling text out of a PDF.

    `error` is set on failure so callers can render a friendly message
    instead of catching exceptions.
    """
    pages: List[DocPage]
    page_count: int                # total pages in the PDF
    total_chars: int               # extracted chars across all pages
    likely_scanned: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_HSPACE_RE = re.compile(r"[ \t\f\v]+")
_LEADING_WS_RE = re.compile(r"\n[ \t]+")
_TRIPLE_NL_RE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalize whitespace and fix common PDF extraction artifacts.

    Safe on empty / None input — returns ''.
    """
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    text = _HSPACE_RE.sub(" ", text)
    text = _LEADING_WS_RE.sub("\n", text)
    text = _TRIPLE_NL_RE.sub("\n\n", text)
    return text.strip()


def naturalize_for_speech(text: str) -> str:
    """Lightly reflow extracted text so it reads more naturally aloud.

    Does NOT rewrite meaning — just joins broken mid-paragraph line breaks.
    """
    text = clean_text(text)
    if not text:
        return ""
    # Join single line breaks that aren't paragraph breaks and don't
    # follow sentence-ending punctuation. The lookbehind also excludes
    # a preceding \n so the second \n of a \n\n pair is left alone.
    text = re.sub(r"(?<![.!?:;\n])\n(?!\n)", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = _HSPACE_RE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def extract_pdf(data: bytes) -> ExtractionResult:
    """Extract text page-by-page from PDF bytes.

    Handles: empty bytes, malformed files, encrypted PDFs (tries empty
    password), scanned/image-only PDFs (flagged via likely_scanned).
    Never raises — always returns an ExtractionResult.
    """
    if not data:
        return ExtractionResult(pages=[], page_count=0, total_chars=0,
                                likely_scanned=False,
                                error="The uploaded file is empty.")

    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover - import guard
        return ExtractionResult(pages=[], page_count=0, total_chars=0,
                                likely_scanned=False,
                                error=f"PDF library not available: {e}")

    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        return ExtractionResult(pages=[], page_count=0, total_chars=0,
                                likely_scanned=False,
                                error=f"Could not open PDF: {e}")

    try:
        # Encrypted PDFs: try empty password (very common case)
        if getattr(pdf, "is_encrypted", False) or getattr(pdf, "needs_pass", False):
            ok = False
            try:
                ok = bool(pdf.authenticate(""))
            except Exception:
                ok = False
            if not ok:
                pdf.close()
                return ExtractionResult(
                    pages=[], page_count=0, total_chars=0,
                    likely_scanned=False,
                    error=("This PDF is password-protected. Please remove "
                           "the password (e.g. open in Preview or Acrobat "
                           "and re-export) and upload again."))

        page_count = pdf.page_count
        if page_count == 0:
            pdf.close()
            return ExtractionResult(pages=[], page_count=0, total_chars=0,
                                    likely_scanned=False,
                                    error="The PDF contains no pages.")

        pages: List[DocPage] = []
        total_chars = 0
        for i in range(page_count):
            raw = ""
            try:
                raw = pdf.load_page(i).get_text("text") or ""
            except Exception:
                # Don't let one bad page kill the whole extraction.
                raw = ""
            cleaned = clean_text(raw)
            # Always append a DocPage so page numbering is preserved even
            # for image-only / blank pages.
            pages.append(DocPage(page_number=i + 1, text=cleaned))
            total_chars += len(cleaned)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    likely_scanned = is_likely_scanned(pages, total_chars)
    return ExtractionResult(pages=pages, page_count=page_count,
                            total_chars=total_chars,
                            likely_scanned=likely_scanned)


def is_likely_scanned(pages: Sequence[DocPage],
                      total_chars: Optional[int] = None) -> bool:
    """True if the PDF appears to be a scanned/image-only document.

    Heuristic: average extractable chars/page is below threshold, OR more
    than 80% of pages have effectively no text.
    """
    if not pages:
        return False
    if total_chars is None:
        total_chars = sum(len(p.text or "") for p in pages)
    avg = total_chars / max(len(pages), 1)
    empty_ratio = sum(1 for p in pages
                      if len((p.text or "").strip()) < 20) / len(pages)
    return avg < SCANNED_PDF_AVG_CHAR_THRESHOLD or empty_ratio > 0.8


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _split_long_page(page: DocPage, max_words: int) -> List[Tuple[int, str]]:
    """Pre-split a single page if it exceeds max_words. Returns (page_no, text)."""
    words = page.text.split()
    if len(words) <= max_words:
        return [(page.page_number, page.text)]
    parts: List[Tuple[int, str]] = []
    for start in range(0, len(words), max_words):
        parts.append((page.page_number,
                      " ".join(words[start:start + max_words])))
    return parts


def chunk_pages(pages: Sequence[DocPage],
                target_words: int = CHUNK_TARGET_WORDS,
                overlap_words: int = CHUNK_OVERLAP_WORDS) -> List[TextChunk]:
    """Split pages into overlapping chunks while preserving page provenance.

    Empty pages are skipped silently. Each chunk tracks the page range it
    came from so citations can be exact.
    """
    if target_words <= 0:
        raise ValueError("target_words must be positive")
    if overlap_words < 0 or overlap_words >= target_words:
        raise ValueError("overlap_words must be in [0, target_words)")

    units: List[Tuple[int, str]] = []
    for page in pages:
        if not (page.text or "").strip():
            continue
        units.extend(_split_long_page(page, target_words))

    chunks: List[TextChunk] = []
    chunk_id = 1
    current_words: List[str] = []
    current_start: Optional[int] = None
    current_end: Optional[int] = None

    for page_number, text in units:
        words = text.split()
        if current_start is None:
            current_start = page_number
            current_end = page_number

        if len(current_words) + len(words) > target_words and current_words:
            chunks.append(TextChunk(
                chunk_id=chunk_id,
                page_start=current_start,
                page_end=current_end or page_number,
                text=" ".join(current_words),
            ))
            chunk_id += 1
            overlap = current_words[-overlap_words:] if overlap_words > 0 else []
            current_words = list(overlap) + words
            current_start = current_end if overlap else page_number
            current_end = page_number
        else:
            current_words.extend(words)
            current_end = page_number

    if current_words:
        chunks.append(TextChunk(
            chunk_id=chunk_id,
            page_start=current_start or 1,
            page_end=current_end or current_start or 1,
            text=" ".join(current_words),
        ))
    return chunks


def chunk_label(chunk: TextChunk) -> str:
    if chunk.page_start == chunk.page_end:
        return f"page {chunk.page_start}"
    return f"pages {chunk.page_start}–{chunk.page_end}"


# ---------------------------------------------------------------------------
# Cosine similarity (no numpy dependency)
# ---------------------------------------------------------------------------

def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def top_k_chunks(query_embedding: Sequence[float],
                 chunks: Sequence[TextChunk],
                 k: int) -> List[Tuple[float, TextChunk]]:
    """Return top-k (score, chunk) pairs by cosine similarity, descending."""
    k = max(1, min(k, MAX_RETRIEVED_CHUNKS))
    scored: List[Tuple[float, TextChunk]] = []
    for c in chunks:
        if c.embedding is None:
            continue
        scored.append((cosine_similarity(query_embedding, c.embedding), c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:k]


# ---------------------------------------------------------------------------
# OpenAI helpers (with retry and friendly errors)
# ---------------------------------------------------------------------------

class OpenAICallError(RuntimeError):
    """Raised when an OpenAI call fails after retries.

    Carries `.user_message` for direct display in the UI.
    """
    def __init__(self, user_message: str, original: Optional[Exception] = None):
        super().__init__(user_message)
        self.user_message = user_message
        self.original = original


def _classify_error_message(detail: str) -> str:
    low = detail.lower()
    if any(s in low for s in ("invalid api key", "incorrect api key",
                              "authentication", "unauthorized", "401")):
        return ("OpenAI rejected the API key. Check OPENAI_API_KEY in the "
                "app's secrets.")
    if "rate limit" in low or "429" in low:
        return ("OpenAI is rate-limiting requests. Please wait a minute "
                "and try again.")
    if any(s in low for s in ("timeout", "timed out", "connection")):
        return ("Could not reach OpenAI (network/timeout). Please try "
                "again in a moment.")
    if "model" in low and ("not found" in low or "does not exist" in low):
        return ("The chat/embedding model name is not available on this "
                "API key. Try the default models.")
    if "context" in low and "length" in low:
        return ("That request is too long for the model. Try a smaller "
                "page range or fewer excerpts.")
    return f"OpenAI request failed: {detail}"


def _retry(fn: Callable, *, what: str,
           max_retries: int = MAX_RETRIES,
           base_delay: float = RETRY_BASE_DELAY,
           sleep: Callable[[float], None] = time.sleep):
    """Run `fn()` with exponential backoff for transient failures.

    Permanent failures (auth, bad request) are not retried.
    """
    last: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - classified below
            last = e
            msg = str(e).lower()
            transient = any(s in msg for s in (
                "timeout", "timed out", "connection", "rate limit",
                "temporarily", "overloaded", "503", "502", "504", "429",
            ))
            permanent = any(s in msg for s in (
                "invalid api key", "incorrect api key", "authentication",
                "unauthorized", "401", "permission",
                "model_not_found", "does not exist",
            ))
            if permanent or attempt == max_retries or not transient:
                break
            sleep(base_delay * (2 ** (attempt - 1)))
    detail = str(last) if last else "unknown error"
    raise OpenAICallError(_classify_error_message(detail) +
                          f" (during {what})", last)


def embed_texts(client, texts: Sequence[str],
                model: str = DEFAULT_EMBED_MODEL,
                batch_size: int = EMBED_BATCH_SIZE,
                progress_cb: Optional[Callable[[int, int], None]] = None
                ) -> List[List[float]]:
    """Embed texts in batches. Raises OpenAICallError on persistent failure."""
    if not texts:
        return []
    out: List[List[float]] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        batch = list(texts[start:start + batch_size])

        def _call():
            return client.embeddings.create(model=model, input=batch)

        resp = _retry(_call, what="embedding generation")
        for item in resp.data:
            out.append(list(item.embedding))
        if progress_cb is not None:
            try:
                progress_cb(min(start + batch_size, total), total)
            except Exception:
                pass
    return out


def chat_complete(client, *, model: str, system: str, user: str,
                  temperature: float = 0.2) -> str:
    """Single chat call using the stable Chat Completions API.

    The Responses API works too, but Chat Completions has the most stable
    surface across SDK versions. Returns plain string.
    """
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
    resp = _retry(_call, what="chat completion")
    return (resp.choices[0].message.content or "").strip()


def answer_with_citations(client, question: str,
                          retrieved: Sequence[Tuple[float, TextChunk]],
                          model: str = DEFAULT_CHAT_MODEL) -> str:
    if not question.strip():
        return "Please enter a question first."
    if not retrieved:
        return ("I could not find anything in the document related to that "
                "question. Try rephrasing, or rebuild the index.")

    blocks = []
    for i, (score, c) in enumerate(retrieved, start=1):
        blocks.append(
            f"Source {i} ({chunk_label(c)}, relevance {score:.2f}):\n{c.text}"
        )
    context = "\n\n---\n\n".join(blocks)
    system = (
        "You are a careful research assistant answering questions about a "
        "single PDF. Use ONLY the provided excerpts. If the answer is not "
        "in the excerpts, say so plainly. Cite page numbers inline like "
        "(p. 12) for every claim. Keep the answer concise and natural."
    )
    user = f"Question: {question}\n\nExcerpts:\n{context}"
    return chat_complete(client, model=model, system=system, user=user,
                         temperature=0.2)


def summarize_chunks(client, chunks: Sequence[TextChunk], style: str,
                     model: str = DEFAULT_CHAT_MODEL) -> str:
    if not chunks:
        return "Nothing to summarize."
    body = "\n\n".join(
        f"[{chunk_label(c)}]\n{c.text}" for c in chunks
    )
    system = (
        "You summarize PDF excerpts clearly and faithfully. Preserve key "
        "facts, names, dates, definitions, and decisions. Cite page "
        "numbers inline like (p. 12). Do not invent details."
    )
    user = f"Summary style: {style}\n\nExcerpts:\n{body}"
    return chat_complete(client, model=model, system=system, user=user,
                         temperature=0.3)


def reduce_summaries(client, partials: Sequence[str], style: str,
                     model: str = DEFAULT_CHAT_MODEL) -> str:
    if len(partials) <= 1:
        return partials[0] if partials else ""
    system = (
        "You combine partial summaries of one PDF into a single coherent "
        "summary. Preserve page citations. Avoid repetition. Do not "
        "invent details."
    )
    user = (f"Combine these partial summaries into one final summary in "
            f"the style: {style}.\n\n" +
            "\n\n---\n\n".join(partials))
    return chat_complete(client, model=model, system=system, user=user,
                         temperature=0.3)


# ---------------------------------------------------------------------------
# Page-range selection
# ---------------------------------------------------------------------------

def select_chunks_in_range(chunks: Sequence[TextChunk],
                           start_page: int, end_page: int,
                           max_chunks: int = MAX_SUMMARY_CHUNKS
                           ) -> List[TextChunk]:
    """Return chunks that overlap [start_page, end_page], capped at max_chunks."""
    if start_page > end_page:
        start_page, end_page = end_page, start_page
    selected = [
        c for c in chunks
        if not (c.page_end < start_page or c.page_start > end_page)
    ]
    return selected[:max_chunks]


def get_pages_text(pages: Sequence[DocPage], start_page: int,
                   end_page: int) -> str:
    if start_page > end_page:
        start_page, end_page = end_page, start_page
    parts = [f"Page {p.page_number}.\n{p.text}"
             for p in pages
             if start_page <= p.page_number <= end_page and p.text]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

# OpenAI TTS hard-limits input to 4096 characters per request.
TTS_MAX_CHARS = 3800

NATURAL_NARRATION = (
    "Read this aloud in a warm, natural, conversational tone — as if a "
    "thoughtful host were narrating to a single listener. Pace yourself, "
    "breathe between paragraphs, let key phrases land. Avoid sounding "
    "robotic or rushed."
)

VOICE_STYLES = {
    "Warm audiobook": (
        "Read like a warm audiobook narrator. Relaxed engaging pace, "
        "natural pauses, expressive but not dramatic intonation."
    ),
    "Alexa-like clear narrator": (
        "Read clearly and naturally, like a polished smart-speaker "
        "narrator. Calm pacing, clean pronunciation, gentle emphasis on "
        "headings."
    ),
    "Slow study mode": (
        "Read slowly and clearly for studying. Pause briefly after "
        "important ideas, definitions, and transitions."
    ),
    "Executive briefing": (
        "Read like a concise executive briefing. Sound professional, "
        "direct, and calm."
    ),
    "Storyteller": (
        "Read with a rich storyteller quality while staying faithful to "
        "the document. Natural pacing and expressive phrasing."
    ),
}


def split_for_tts(text: str, max_chars: int = TTS_MAX_CHARS) -> List[str]:
    """Split text into TTS-sized clips on paragraph/sentence boundaries."""
    text = naturalize_for_speech(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n\s*\n", text)
    parts: List[str] = []
    current = ""

    def flush():
        nonlocal current
        if current.strip():
            parts.append(current.strip())
        current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            # Split this paragraph by sentence
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(current) + len(sent) + 1 <= max_chars:
                    current = (current + " " + sent).strip() if current else sent
                else:
                    flush()
                    # If a single sentence is somehow > max_chars, hard-cut it
                    while len(sent) > max_chars:
                        parts.append(sent[:max_chars])
                        sent = sent[max_chars:]
                    current = sent
        elif len(current) + len(para) + 2 <= max_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            flush()
            current = para
    flush()
    return parts


def tts_clip(client, text: str, *, voice: str = "alloy",
             instructions: Optional[str] = None,
             model: str = DEFAULT_TTS_MODEL) -> bytes:
    """Generate one MP3 clip. Returns raw bytes (no temp files)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Cannot generate audio for empty text.")
    if len(text) > TTS_MAX_CHARS + 200:
        # Defensive truncation; callers should split first.
        text = text[:TTS_MAX_CHARS]

    kwargs = dict(model=model, voice=voice, input=text, response_format="mp3")
    if instructions:
        kwargs["instructions"] = instructions

    def _call():
        resp = client.audio.speech.create(**kwargs)
        # Normalize across SDK shapes
        if hasattr(resp, "read"):
            return resp.read()
        if hasattr(resp, "content"):
            return resp.content
        if hasattr(resp, "iter_bytes"):
            return b"".join(resp.iter_bytes())
        raise RuntimeError("Unexpected TTS response shape from OpenAI SDK.")

    return _retry(_call, what="audio generation")
