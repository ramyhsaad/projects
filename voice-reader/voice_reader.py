#!/usr/bin/env python3
"""
voice_reader.py: read a PDF aloud in a cloned voice with Chatterbox.

    python voice_reader.py BOOK.pdf REF.wav OUT.mp3 [--pages 2-66]
        [--expression 0.6] [--pace 0.5] [--device auto|cpu|mps|cuda]

How it stays fast and safe to stop:
- The text is split into short passages (one or two sentences, about 250
  characters). A short passage finishes long before Chatterbox's
  1000-step limit, so the voice can't ramble on for hours.
- Each passage is saved as a WAV in OUT.parts/ as soon as it's made. Run
  the same command again after stopping (Ctrl-C) and it skips finished
  passages.
- Progress is one line per passage: passage X of N, time spent, time left.
- At the end all passages are joined, with short pauses, into OUT.mp3.
- Lecture or chapter headings (larger type in the PDF, or pages given with
  --break-pages) get a long pause before them and a chapter marker.
- --speed slows the voice without lowering it (default 0.9).
- pronunciations.txt respells words before they're spoken (Zat = Zaht).

Run with --bench to time one passage on each device (cpu, mps) before
committing to a long book.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

# Hide the per-step "Sampling …/1000" bars before tqdm is imported.
os.environ.setdefault("TQDM_DISABLE", "1")
# Let MPS fall back to CPU for ops it doesn't support instead of failing.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

PASSAGE_MAX_CHARS = 250
PAUSE_SENTENCE_S = 0.40   # between passages in the same paragraph
PAUSE_PARAGRAPH_S = 1.00  # between paragraphs
PAUSE_AFTER_HEADING_S = 1.50
PAUSE_LECTURE_S = 4.00    # before a new lecture or chapter
DEFAULT_SPEED = 0.90
HEADING_SIZE_RATIO = 1.15  # type this much larger than body text is a heading
# Rough speaking rate used to spot a passage that rambled past its text.
SECONDS_PER_CHAR = 0.075


# ---------------------------------------------------------------------------
# PDF text
# ---------------------------------------------------------------------------

def parse_pages(spec: Optional[str], page_count: int) -> List[int]:
    """'2-66' or '1,3,5-7' -> sorted 1-based page numbers within the PDF."""
    if not spec:
        return list(range(1, page_count + 1))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else page_count
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(f"Can't read page range '{part}'. Use e.g. 2-66 or 1,3,5-7.")
        if a > b:
            a, b = b, a
        pages.update(range(max(1, a), min(page_count, b) + 1))
    if not pages:
        raise ValueError(f"No pages in '{spec}' (the PDF has {page_count} pages).")
    return sorted(pages)


def _clean(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # re-join hyphenated words
    text = re.sub(r"[ \t\f\v ]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


_PAGE_NUMBER_RE = re.compile(r"^(page\s*)?[\divxlc]{1,7}(\s*(of|/)\s*\d{1,5})?$", re.I)


def _edge_key(text: str) -> str:
    return re.sub(r"[^a-z#]+", " ", re.sub(r"\d+", "#", text.lower())).strip()


def strip_running_lines(pages: Sequence[Sequence[str]]) -> List[List[str]]:
    """Drop page numbers and short headers/footers that repeat across pages."""
    drops = running_line_drops(pages)
    return [[b for i, b in enumerate(blocks) if i not in d] for blocks, d in zip(pages, drops)]


def running_line_drops(pages: Sequence[Sequence[str]]) -> List[set]:
    """For each page, the indexes of blocks that are page numbers or running headers/footers."""
    def edges(blocks):
        n = len(blocks)
        return sorted({i for i in (0, 1, n - 2, n - 1) if 0 <= i < n})

    counts: dict = {}
    for blocks in pages:
        for key in {_edge_key(blocks[i]) for i in edges(blocks)}:
            if key and key != "#":
                counts[key] = counts.get(key, 0) + 1
    threshold = max(3, math.ceil(len(pages) * 0.3))
    out = []
    for blocks in pages:
        drop = set()
        for i in edges(blocks):
            t = blocks[i].strip()
            k = _edge_key(t)
            if _PAGE_NUMBER_RE.match(t) or (k and counts.get(k, 0) >= threshold and len(t) < 100):
                drop.add(i)
        out.append(drop)
    return out


@dataclass
class Para:
    text: str
    page: int
    heading: bool = False


def _speakable_heading(text: str) -> str:
    """ALL-CAPS headings read better in title case (the voice may spell capitals)."""
    if text.isupper():
        small = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to"}
        words = text.lower().split()
        text = " ".join(w if (i and w in small) else w.capitalize() for i, w in enumerate(words))
    return text


def extract_paragraphs(pdf_path: Path, page_spec: Optional[str]) -> Tuple[List[Para], List[int]]:
    """Return (paragraphs in reading order, the page numbers used).

    A short block set in larger type than the body text is marked as a heading.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz  # older PyMuPDF
        except ImportError:
            fitz = None
    if fitz is None:
        sys.exit("PyMuPDF is missing. Run: pip install pymupdf")

    doc = fitz.open(pdf_path)
    if doc.needs_pass and not doc.authenticate(""):
        sys.exit("This PDF is password-protected. Export an unlocked copy first.")
    wanted = parse_pages(page_spec, doc.page_count)

    # Headers/footers are judged across the whole book, not just the chosen pages.
    all_blocks: List[List[Tuple[str, float]]] = []
    size_chars: dict = {}
    for i in range(doc.page_count):
        blocks = []
        for b in doc.load_page(i).get_text("dict", sort=True)["blocks"]:
            if b.get("type") != 0:
                continue  # image
            lines, sizes = [], {}
            for line in b.get("lines", []):
                lines.append("".join(sp["text"] for sp in line["spans"]))
                for sp in line["spans"]:
                    n = len(sp["text"].strip())
                    if n:
                        sizes[round(sp["size"], 1)] = sizes.get(round(sp["size"], 1), 0) + n
            t = _clean("\n".join(lines))
            if t and sizes:
                size = max(sizes, key=sizes.get)
                blocks.append((t, size))
                for k, v in sizes.items():
                    size_chars[k] = size_chars.get(k, 0) + v
        all_blocks.append(blocks)
    doc.close()
    body_size = max(size_chars, key=size_chars.get) if size_chars else 0
    drops = running_line_drops([[t for t, _ in blocks] for blocks in all_blocks])

    paras: List[Para] = []
    for pno in wanted:
        kept = [b for i, b in enumerate(all_blocks[pno - 1]) if i not in drops[pno - 1]]
        for k, (block, size) in enumerate(kept):
            text = re.sub(r"(?<![.!?:;])\n", " ", block)       # join wrapped lines
            text = re.sub(r"\n+", " ", text)
            text = re.sub(r"\[\d+(?:\s*[-–,]\s*\d+)*\]", "", text)  # [12] citations
            text = re.sub(r"\bhttps?://\S+|\bwww\.\S+", "", text, flags=re.I)
            text = re.sub(r"\s+", " ", text).strip()
            text = re.sub(r" +([,.;:!?])", r"\1", text)
            if not re.search(r"[A-Za-z]", text):
                continue
            heading = (body_size > 0 and size >= body_size * HEADING_SIZE_RATIO
                       and len(text) <= 120)
            if heading:
                # Consecutive heading lines ("Chapter 3" / "The Soul's Journey") are one heading.
                if paras and paras[-1].heading and paras[-1].page == pno:
                    paras[-1].text += ". " + _speakable_heading(text)
                else:
                    paras.append(Para(_speakable_heading(text), pno, True))
            # A sentence that runs over a page turn stays in one paragraph.
            elif (k == 0 and paras and not paras[-1].heading
                  and not re.search(r"[.!?:;\"”’)\]]$", paras[-1].text)):
                paras[-1].text += " " + text
            else:
                paras.append(Para(text, pno))
    return paras, wanted


# ---------------------------------------------------------------------------
# Pronunciation
# ---------------------------------------------------------------------------

def load_pronunciations(path: Optional[Path]) -> List[Tuple[str, str]]:
    """Read 'word = respelling' lines. '#' starts a comment."""
    if not path or not path.exists():
        return []
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            word, say = (x.strip() for x in line.split("=", 1))
            if word and say:
                pairs.append((word, say))
    return pairs


def apply_pronunciations(text: str, pairs: Sequence[Tuple[str, str]]) -> str:
    """Replace whole words, ignoring case, keeping a leading capital."""
    for word, say in pairs:
        def sub(m, say=say):
            return say[:1].upper() + say[1:] if m.group(0)[:1].isupper() else say
        text = re.sub(rf"(?<![\w'’]){re.escape(word)}(?![\w])", sub, text, flags=re.I)
    return text


# ---------------------------------------------------------------------------
# Passages
# ---------------------------------------------------------------------------

@dataclass
class Passage:
    index: int
    text: str
    paragraph_end: bool  # a longer pause follows
    page: int = 0
    heading: bool = False
    break_before: bool = False  # a new lecture or chapter starts here


_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+[\"”’)\]]*|$)\s*")


def _split_long(sentence: str, max_chars: int) -> List[str]:
    """Split one over-long sentence at ; : , — then at spaces."""
    out, cur = [], ""
    for piece in re.split(r"(?<=[;:,—–])\s+", sentence):
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if cur:
                out.append(cur)
                cur = ""
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if cur and len(cur) + 1 + len(piece) > max_chars:
            out.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur:
        out.append(cur)
    return [p for p in out if p]


def make_passages(paragraphs: Sequence, max_chars: int = PASSAGE_MAX_CHARS,
                  break_pages: Sequence[int] = ()) -> List[Passage]:
    """Pack whole sentences into passages of at most max_chars, never across paragraphs.

    Paragraphs may be plain strings or Para. A heading, or the first paragraph
    on a page in break_pages, starts a new lecture (break_before).
    """
    passages: List[Passage] = []
    pending_breaks = set(break_pages)
    for item in paragraphs:
        para = item if isinstance(item, Para) else Para(item, 0)
        brk = False
        if para.page in pending_breaks:
            pending_breaks.discard(para.page)
            brk = True
        if para.heading:
            brk = True
        if brk and passages and passages[-1].heading:
            brk = False  # already breaking for the heading just before
        chunks: List[str] = []
        cur = ""
        for m in _SENTENCE_RE.finditer(para.text):
            sent = m.group(0).strip()
            if not sent:
                continue
            pieces = _split_long(sent, max_chars) if len(sent) > max_chars else [sent]
            for piece in pieces:
                if cur and len(cur) + 1 + len(piece) > max_chars:
                    chunks.append(cur)
                    cur = piece
                else:
                    cur = f"{cur} {piece}".strip()
        if cur:
            chunks.append(cur)
        for j, c in enumerate(chunks):
            passages.append(Passage(len(passages), c, j == len(chunks) - 1, para.page,
                                    para.heading, brk and j == 0))
    return passages


# ---------------------------------------------------------------------------
# Speech engines
# ---------------------------------------------------------------------------

def pick_device(requested: str) -> str:
    import torch
    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if requested == "mps" and not torch.backends.mps.is_available():
        print("  MPS isn't available here, using cpu.")
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        print("  CUDA isn't available here, using cpu.")
        return "cpu"
    return requested


class ChatterboxEngine:
    def __init__(self, ref_wav: Path, device: str, model: str,
                 expression: float, pace: float, temperature: float):
        import torch
        self.torch = torch
        self.device = pick_device(device)
        self.kind = model
        self.expression, self.pace, self.temperature = expression, pace, temperature
        t0 = time.time()
        if model == "turbo":
            try:
                from chatterbox.tts_turbo import ChatterboxTurboTTS
            except ImportError:
                sys.exit("This chatterbox-tts has no Turbo model. Run: pip install -U chatterbox-tts")
            self.model = ChatterboxTurboTTS.from_pretrained(device=self.device)
        else:
            from chatterbox.tts import ChatterboxTTS
            self.model = ChatterboxTTS.from_pretrained(device=self.device)
        self._quiet_progress_bars()
        # Encode the reference voice once, not once per passage.
        self.model.prepare_conditionals(str(ref_wav), exaggeration=expression)
        self.sr = self.model.sr
        print(f"  Loaded Chatterbox{' Turbo' if model == 'turbo' else ''} on {self.device} "
              f"in {time.time() - t0:.0f} s.")

    @staticmethod
    def _quiet_progress_bars():
        """Replace the per-step tqdm bar inside Chatterbox with a no-op."""
        def passthrough(it=None, *a, **k):
            return it
        for name in ("chatterbox.models.t3.t3", "chatterbox.models.s3gen.flow_matching"):
            mod = sys.modules.get(name)
            if mod is not None and hasattr(mod, "tqdm"):
                mod.tqdm = passthrough

    def speak(self, text: str):
        """Return float32 mono samples (numpy) at self.sr."""
        with self.torch.inference_mode():
            if self.kind == "turbo":
                wav = self.model.generate(text, temperature=self.temperature)
            else:
                wav = self.model.generate(text, exaggeration=self.expression,
                                          cfg_weight=self.pace, temperature=self.temperature)
        return wav.squeeze().detach().float().cpu().numpy()


class FakeEngine:
    """Tones instead of speech, for testing without a model (--engine fake)."""
    def __init__(self, *a, **k):
        self.sr = 24000
        self.device = "fake"

    def speak(self, text: str):
        import numpy as np
        secs = max(0.4, len(text) * SECONDS_PER_CHAR)
        t = np.arange(int(secs * self.sr)) / self.sr
        delay = float(os.environ.get("VOICE_READER_FAKE_DELAY", "0"))
        if delay:
            time.sleep(delay)
        return (0.2 * np.sin(2 * np.pi * 220 * t)).astype("float32")


# ---------------------------------------------------------------------------
# Audio files
# ---------------------------------------------------------------------------

def write_wav(path: Path, samples, sr: int) -> None:
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    tmp = path.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)  # a half-written file never looks finished


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def trim_silence(samples, sr: int, threshold: float = 0.01, keep_s: float = 0.05):
    import numpy as np
    loud = np.flatnonzero(np.abs(samples) > threshold)
    if loud.size == 0:
        return samples
    keep = int(keep_s * sr)
    return samples[max(0, loud[0] - keep): min(len(samples), loud[-1] + keep)]


def gap_after(cur: Passage, nxt: Passage, pause_scale: float = 1.0) -> float:
    if nxt.break_before:
        gap = PAUSE_LECTURE_S
    elif cur.heading:
        gap = PAUSE_AFTER_HEADING_S
    elif cur.paragraph_end:
        gap = PAUSE_PARAGRAPH_S
    else:
        gap = PAUSE_SENTENCE_S
    return gap * pause_scale


def join_parts(parts: Sequence[Tuple[Path, Passage]], out_wav: Path,
               pause_scale: float = 1.0) -> Tuple[float, List[Tuple[float, str]]]:
    """Concatenate WAVs with pauses. Returns (total seconds, [(start s, title)] per lecture)."""
    sr = None
    chapters: List[Tuple[float, str]] = []
    frames = 0
    with wave.open(str(out_wav), "wb") as out:
        for i, (path, p) in enumerate(parts):
            with wave.open(str(path), "rb") as w:
                if sr is None:
                    sr = w.getframerate()
                    out.setnchannels(1)
                    out.setsampwidth(2)
                    out.setframerate(sr)
                if i == 0 or p.break_before:
                    title = p.text if p.heading else f"Part {len(chapters) + 1}"
                    chapters.append((frames / sr, title[:80]))
                out.writeframes(w.readframes(w.getnframes()))
                frames += w.getnframes()
            if i < len(parts) - 1:
                gap = int(gap_after(p, parts[i + 1][1], pause_scale) * sr)
                out.writeframes(b"\x00\x00" * gap)
                frames += gap
        total = frames / sr if sr else 0.0
    return total, chapters


def to_mp3(wav_path: Path, mp3_path: Path, title: str, speed: float = 1.0,
           chapters: Sequence[Tuple[float, str]] = (), total: float = 0.0) -> bool:
    """Encode the MP3, slowed to `speed` (pitch kept) and with chapter markers."""
    if not shutil.which("ffmpeg"):
        return False
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path)]
    meta = None
    if len(chapters) > 1:
        meta = wav_path.with_name("chapters.txt")
        esc = lambda t: re.sub(r"([=;#\\\n])", r"\\\1", t)
        lines = [";FFMETADATA1", f"title={esc(title)}"]
        ends = [c[0] for c in chapters[1:]] + [total]
        for (start, name), end in zip(chapters, ends):
            lines += ["[CHAPTER]", "TIMEBASE=1/1000",
                      f"START={int(start / speed * 1000)}", f"END={int(end / speed * 1000)}",
                      f"title={esc(name)}"]
        meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd += ["-i", str(meta), "-map_metadata", "1", "-map_chapters", "1", "-map", "0:a"]
    if abs(speed - 1.0) > 0.001:
        cmd += ["-af", f"atempo={speed}"]
    cmd += ["-codec:a", "libmp3lame", "-b:a", "96k", "-ac", "1", "-id3v2_version", "3",
            "-metadata", f"title={title}", str(mp3_path)]
    ok = subprocess.run(cmd).returncode == 0
    if meta:
        meta.unlink(missing_ok=True)
    return ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fmt_time(s: float) -> str:
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {sec:02d}s"


def passage_file(work: Path, p: Passage, settings_key: str) -> Path:
    digest = hashlib.sha1(f"{settings_key}|{p.text}".encode()).hexdigest()[:10]
    return work / f"{p.index + 1:05d}-{digest}.wav"


def make_engine(args):
    if args.engine == "fake":
        return FakeEngine()
    try:
        import chatterbox  # noqa: F401
    except ImportError:
        sys.exit("Chatterbox is missing. Run: pip install chatterbox-tts  (or use read.sh, which sets it up)")
    return ChatterboxEngine(args.ref, args.device, args.model,
                            args.expression, args.pace, args.temperature)


def bench(args, passages: List[Passage]) -> None:
    """Time the same passage on each available device."""
    import torch
    sample = max(passages[:20], key=lambda p: len(p.text)) if passages else Passage(0, "This is a short test of the voice.", True)
    devices = ["cpu"]
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        devices.append("mps")
    if torch.cuda.is_available():
        devices.append("cuda")
    print(f"Timing one passage ({len(sample.text)} characters) on: {', '.join(devices)}\n")
    for dev in devices:
        args.device = dev
        eng = make_engine(args)
        eng.speak("Warm up.")
        t0 = time.time()
        audio = eng.speak(sample.text)
        took = time.time() - t0
        secs = len(audio) / eng.sr
        print(f"  {dev:>4}: {took:5.1f} s to make {secs:4.1f} s of speech "
              f"({took / max(secs, 0.1):.1f}x real time)\n")
        del eng
    print("Use the fastest with --device. Under about 3x real time is good; "
          "over 20x usually means the Mac is out of memory (quit other apps).")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read a PDF aloud in a cloned voice (Chatterbox).")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("ref", type=Path, help="reference voice WAV, 10-20 s of clean speech")
    ap.add_argument("out", type=Path, nargs="?", help="output MP3 (default: <pdf name>.mp3)")
    ap.add_argument("--pages", help="e.g. 2-66 or 1,3,5-7 (default: all)")
    ap.add_argument("--expression", type=float, default=0.5,
                    help="emotion, 0.25 flat to 1.0 dramatic (Chatterbox exaggeration)")
    ap.add_argument("--pace", type=float, default=0.5,
                    help="lower is slower and more deliberate, 0.2-0.8 (Chatterbox cfg_weight)")
    ap.add_argument("--speed", type=float, default=DEFAULT_SPEED,
                    help="final playback speed, pitch kept: 0.8 slower, 1.0 as made (default 0.9)")
    ap.add_argument("--pauses", type=float, default=1.0,
                    help="multiply every pause, e.g. 1.5 for longer silences")
    ap.add_argument("--break-pages", default="",
                    help="pages where a new lecture starts, e.g. 5,19,33 (headings are found automatically)")
    ap.add_argument("--pronounce", type=Path,
                    default=Path(__file__).resolve().with_name("pronunciations.txt"),
                    help="file of 'word = respelling' lines (default: pronunciations.txt)")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    ap.add_argument("--model", default="standard", choices=["standard", "turbo"],
                    help="turbo is several times faster; it ignores --expression and --pace")
    ap.add_argument("--max-chars", type=int, default=PASSAGE_MAX_CHARS,
                    help="longest passage in characters (default 250)")
    ap.add_argument("--bench", action="store_true", help="time one passage on each device and stop")
    ap.add_argument("--dry-run", action="store_true", help="show the passages and stop")
    ap.add_argument("--fresh", action="store_true", help="ignore saved passages and start over")
    ap.add_argument("--engine", default="chatterbox", choices=["chatterbox", "fake"],
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if not args.pdf.exists():
        sys.exit(f"Can't find the PDF: {args.pdf}")
    if args.engine != "fake" and not args.dry_run and not args.ref.exists():
        sys.exit(f"Can't find the voice file: {args.ref}")
    out = args.out or args.pdf.with_suffix(".mp3")
    if out.suffix.lower() != ".mp3":
        out = out.with_suffix(".mp3")

    if not 0.5 <= args.speed <= 2.0:
        sys.exit("--speed must be between 0.5 and 2.0.")
    try:
        break_pages = [int(x) for x in args.break_pages.replace(" ", "").split(",") if x]
    except ValueError:
        sys.exit("--break-pages takes page numbers like 5,19,33")

    paras, pages = extract_paragraphs(args.pdf, args.pages)
    passages = make_passages(paras, args.max_chars, break_pages)
    if not passages:
        sys.exit("No readable text on those pages. If the PDF is scanned, run OCR on it first.")
    respell = load_pronunciations(args.pronounce)
    for p in passages:
        p.text = apply_pronunciations(p.text, respell)
    lectures = sum(1 for p in passages if p.break_before)
    total_chars = sum(len(p.text) for p in passages)
    print(f"{args.pdf.name}: pages {pages[0]}-{pages[-1]}, {len(passages)} passages, "
          f"{total_chars:,} characters (about {fmt_time(total_chars * SECONDS_PER_CHAR / args.speed)} of audio).")
    print(f"  {lectures} lecture/chapter breaks; {len(respell)} pronunciation fixes"
          f"{' from ' + args.pronounce.name if respell else ''}; speed {args.speed:g}.")

    if args.dry_run:
        for p in passages:
            if p.break_before:
                print(f"\n======== new lecture (page {p.page}) ========")
            mark = "## " if p.heading else ""
            print(f"[{p.index + 1}] {mark}{p.text}" + ("\n" if p.paragraph_end else ""))
        return 0
    if args.bench:
        bench(args, passages)
        return 0

    work = out.with_name(out.stem + ".parts")
    if args.fresh and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    settings_key = json.dumps([args.model, args.expression, args.pace, args.temperature,
                               args.ref.name, args.engine])
    files = [passage_file(work, p, settings_key) for p in passages]
    todo = [i for i, f in enumerate(files) if not f.exists()]
    done_before = len(passages) - len(todo)
    if done_before:
        print(f"Picking up where it stopped: {done_before} of {len(passages)} passages already made.")

    if todo:
        engine = make_engine(args)
        stop = {"now": False}

        def on_sigint(sig, frame):
            if stop["now"]:
                raise KeyboardInterrupt
            stop["now"] = True
            print("\n  Stopping after this passage (Ctrl-C again to stop at once). "
                  "Run the same command to continue.")
        signal.signal(signal.SIGINT, on_sigint)

        t_start = time.time()
        todo_chars = sum(len(passages[i].text) for i in todo)
        chars_done = 0
        audio_made = 0.0
        warned_slow = False
        for n, i in enumerate(todo, 1):
            p = passages[i]
            t0 = time.time()
            samples = engine.speak(p.text)
            secs = len(samples) / engine.sr
            # A passage far longer than its text means the voice rambled. Try once more.
            limit = max(12.0, len(p.text) * SECONDS_PER_CHAR * 3)
            if secs > limit:
                print(f"  Passage {i + 1} ran {secs:.0f} s for {len(p.text)} characters; retrying it.")
                retry = engine.speak(p.text)
                if len(retry) < len(samples):
                    samples, secs = retry, len(retry) / engine.sr
            samples = trim_silence(samples, engine.sr)
            write_wav(files[i], samples, engine.sr)

            took = time.time() - t0
            chars_done += len(p.text)
            audio_made += secs
            elapsed = time.time() - t_start
            left = elapsed / chars_done * (todo_chars - chars_done)
            print(f"Passage {i + 1} of {len(passages)}  ({took:4.1f} s, "
                  f"{took / max(secs, 0.1):4.1f}x real time)  "
                  f"elapsed {fmt_time(elapsed)}, about {fmt_time(left)} left", flush=True)
            if not warned_slow and n >= 3 and elapsed / max(audio_made, 0.1) > 20:
                warned_slow = True
                print("  This is very slow. Quit other apps (the Mac may be swapping), "
                      "or stop and compare devices with --bench.", flush=True)
            if stop["now"]:
                print(f"Stopped. {done_before + n} of {len(passages)} passages are saved in {work}/")
                return 130
        signal.signal(signal.SIGINT, signal.default_int_handler)

    print("Joining passages…")
    full_wav = work / "full.wav"
    total, chapters = join_parts([(files[i], passages[i]) for i in range(len(passages))],
                                 full_wav, args.pauses)
    title = args.pdf.stem
    if to_mp3(full_wav, out, title, args.speed, chapters, total):
        full_wav.unlink()
        print(f"Done: {out} ({fmt_time(total / args.speed)}, {len(chapters)} chapters).")
        print(f"Saved passages are in {work}/. Delete that folder once you're happy with the MP3.")
    else:
        wav_out = out.with_suffix(".wav")
        shutil.move(str(full_wav), wav_out)
        print(f"ffmpeg isn't installed, so I saved a WAV instead: {wav_out} ({fmt_time(total)}).")
        print("It isn't slowed and has no chapter markers. For the MP3, run: brew install ffmpeg"
              "   then run this command again (nothing is remade).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped. Finished passages are saved; run the same command to continue.")
        sys.exit(130)
