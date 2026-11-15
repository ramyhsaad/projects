#!/usr/bin/env python3
"""Read a PDF aloud in a cloned voice (Chatterbox) and save one MP3/M4A.

    python voice_reader.py BOOK.pdf VOICE.wav OUT.mp3 [--pages 2-66] [options]

What it does differently from a plain "read every page" loop:
  * Short passages (1-2 sentences), so no passage runs to Chatterbox's
    1000-token cap (about 40 s of audio).
  * Pauses: short between passages, longer between paragraphs, long before
    each lecture/chapter heading.
  * pronunciations.txt: "word = how to say it", applied before speaking.
  * --speed slows the finished audio without changing the pitch.
  * Every passage is saved in OUT.parts/ as it is made. Run the same command
    again and finished passages are reused, so stopping loses nothing, and a
    changed pronunciation only remakes the passages that use that word.
  * --dry-run and --list-chapters show what will be read without loading
    the model.
"""
import argparse
import hashlib
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
import wave
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- PDF text


def page_texts(pdf_path):
    """Return a list of (page_number, text) for every page."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        return [(i + 1, p.get_text()) for i, p in enumerate(doc)]
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("Needs a PDF library: pip install pypdf")
    reader = PdfReader(pdf_path)
    return [(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]


def parse_pages(spec, last):
    if not spec:
        return set(range(1, last + 1))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b or last) + 1))
        elif part:
            pages.add(int(part))
    return {p for p in pages if 1 <= p <= last}


ROMAN = re.compile(r"^[ivxlcdm]+$", re.I)


def is_page_number(line):
    s = line.strip(" -–—.·|")
    return bool(re.fullmatch(r"\d{1,4}", s)) or (bool(ROMAN.match(s)) and len(s) <= 6)


def shape(line):
    """A line with its digits blanked, to spot running headers/footers."""
    return re.sub(r"\d+", "#", line.strip().lower())


def find_running_lines(pages):
    """Lines that repeat at the top or bottom of many pages."""
    if len(pages) < 4:
        return set()
    counts = Counter()
    for _, text in pages:
        lines = [l for l in text.splitlines() if l.strip()]
        for l in set(lines[:2] + lines[-2:]):
            counts[shape(l)] += 1
    limit = max(3, int(len(pages) * 0.3))
    # Running heads don't end like sentences, so a repeated sentence ending is kept.
    return {s for s, n in counts.items()
            if n >= limit and len(s) < 90 and not (len(s) > 25 and s[-1] in ".!?")}


HEADING_WORDS = re.compile(
    r"^(chapter|part|lecture|section|book|introduction|preface|foreword|prologue|epilogue|"
    r"conclusion|appendix|contents)\b",
    re.I,
)


def looks_like_heading(line, custom=None):
    s = line.strip()
    if not s or len(s) > 70 or is_page_number(s):
        return False
    if custom is not None:
        return bool(custom.search(s))
    if s[-1] in ".,;:" or s[0].islower():
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 3 and all(c.isupper() for c in letters):
        return True
    if HEADING_WORDS.match(s) and len(s.split()) <= 8:
        return True
    if re.match(r"^([IVXLC]+|\d{1,2})[.)]?\s+[A-Z]", s) and len(s.split()) <= 9:
        return True
    return False


def clean_inline(text):
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"\s*\[\d+(?:[,–-]\s*\d+)*\]", "", text)  # [12] citation marks
    text = re.sub(r"(?<=[a-z.,;])\d{1,3}(?=\s|$)", "", text)  # footnote numbers
    text = text.replace("­", "")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text.strip()


def structure(pages, wanted, heading_re=None):
    """Turn pages into blocks: ("heading", text, page) / ("para", text, page)."""
    running = find_running_lines(pages)
    lines = []  # (page, line)
    for num, text in pages:
        if num not in wanted:
            continue
        for l in text.splitlines():
            if not l.strip() or is_page_number(l) or shape(l) in running:
                continue
            lines.append((num, l.rstrip()))
    lengths = [len(l.strip()) for _, l in lines if len(l.strip()) > 20]
    full = statistics.median(lengths) if lengths else 60

    blocks, buf, buf_page = [], [], None

    def flush():
        nonlocal buf, buf_page
        if buf:
            text = clean_inline(" ".join(buf))
            if text:
                blocks.append(("para", text, buf_page))
        buf, buf_page = [], None

    for i, (page, raw) in enumerate(lines):
        line = raw.strip()
        if looks_like_heading(line, heading_re):
            flush()
            # Two heading lines in a row ("LECTURE I" / "THE SOUL") become one.
            if blocks and blocks[-1][0] == "heading" and blocks[-1][2] == page:
                blocks[-1] = ("heading", blocks[-1][1] + ". " + line, page)
            else:
                blocks.append(("heading", line, page))
            continue
        if buf_page is None:
            buf_page = page
        if buf and buf[-1].endswith("-") and line[:1].islower():
            buf[-1] = buf[-1][:-1] + line  # re-join a hyphenated word
        else:
            buf.append(line)
        indented = raw[:1].isspace() and not raw.startswith(" " * 8)
        nxt = lines[i + 1][1] if i + 1 < len(lines) else ""
        ends_sentence = re.search(r"[.!?:'\"’”)]$", line) is not None
        if ends_sentence and (len(line) < 0.8 * full or (nxt[:1].isspace() and not indented)):
            flush()
    flush()
    return [(k, clean_inline(t) if k == "heading" else t, p) for k, t, p in blocks]


# ---------------------------------------------------------- pronunciations


def load_pronunciations(paths):
    rules = []
    for path in paths:
        if not path or not Path(path).exists():
            continue
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "=" not in line:
                continue
            word, say = (x.strip() for x in line.split("=", 1))
            if word and say:
                rules.append((re.compile(r"(?<![\w’'])" + re.escape(word) + r"(?![\w])", re.I), say))
    return rules


def apply_pronunciations(text, rules):
    for pattern, say in rules:
        def repl(m, say=say):
            orig = m.group(0)
            if orig.isupper() and len(orig) > 1:
                return say.upper()
            if orig[:1].isupper():
                return say[:1].upper() + say[1:]
            return say
        text = pattern.sub(repl, text)
    return text


# ----------------------------------------------------------------- passages

SENT_END = re.compile(r"(?<=[.!?…])[\"'’”)\]]*\s+(?=[\"'‘“(\[]?[A-Z0-9])")
ABBREV = re.compile(r"\b(Mr|Mrs|Ms|Dr|St|Prof|cf|e\.g|i\.e|vs|etc|p|pp|vol|ch|no)\.$", re.I)


def sentences(text):
    parts, out = SENT_END.split(text), []
    for p in parts:
        if out and ABBREV.search(out[-1]):
            out[-1] += " " + p
        else:
            out.append(p)
    return [s.strip() for s in out if s.strip()]


def split_long(sentence, limit):
    if len(sentence) <= limit:
        return [sentence]
    pieces = re.split(r"(?<=[;:,—–])\s+", sentence)
    out, cur = [], ""
    for p in pieces:
        if len(p) > limit:  # no punctuation to split on: split on words
            words, p = p.split(), ""
            for w in words:
                if len(p) + len(w) + 1 > limit and p:
                    out.append((cur + " " + p).strip() if cur else p)
                    cur, p = "", ""
                p = (p + " " + w).strip()
        if cur and len(cur) + len(p) + 1 > limit:
            out.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        out.append(cur)
    return out


def passages_for(text, limit):
    out, cur = [], ""
    for s in sentences(text):
        for piece in split_long(s, limit):
            if cur and len(cur) + len(piece) + 1 > limit:
                out.append(cur)
                cur = piece
            else:
                cur = (cur + " " + piece).strip()
    if cur:
        out.append(cur)
    return out


def plan(blocks, args, rules):
    """List of dicts: text (as spoken), shown, page, pause (s after), chapter."""
    items, chapter = [], 0
    if args.intro:
        items.append(dict(text=apply_pronunciations(args.intro, rules), shown=args.intro,
                          page=0, pause=args.chapter_pause, chapter=0, heading=True))
    for kind, text, page in blocks:
        if kind == "heading":
            chapter += 1
            if items:
                items[-1]["pause"] = max(items[-1]["pause"], args.chapter_pause)
            items.append(dict(text=apply_pronunciations(text, rules), shown=text, page=page,
                              pause=args.heading_pause, chapter=chapter, heading=True))
            continue
        ps = passages_for(text, args.max_chars)
        for j, p in enumerate(ps):
            items.append(dict(text=apply_pronunciations(p, rules), shown=p, page=page,
                              pause=args.para_pause if j == len(ps) - 1 else args.passage_pause,
                              chapter=chapter, heading=False))
    if items:
        items[-1]["pause"] = 1.5
    return items


# -------------------------------------------------------------------- audio


def write_wav(path, samples, sr):
    import numpy as np

    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    tmp = str(path) + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def read_wav(path):
    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return data.astype("float32") / 32767, sr


def level(x, target_rms=0.07, peak=0.9):
    """Even out loudness between passages and keep peaks from clipping."""
    import numpy as np

    if len(x) == 0:
        return x
    rms = float(np.sqrt(np.mean(x ** 2)))
    if rms > 1e-4:
        x = x * (target_rms / rms)
    top = float(np.abs(x).max())
    if top > peak:
        x = x * (peak / top)
    return x.astype("float32")


def trim_silence(x, sr, margin=0.04):
    import numpy as np

    if len(x) == 0:
        return x
    loud = np.flatnonzero(np.abs(x) > max(0.01, 0.02 * float(np.abs(x).max())))
    if len(loud) == 0:
        return x[:0]
    m = int(margin * sr)
    return x[max(0, loud[0] - m): loud[-1] + m]


def fmt_time(s):
    s = int(s)
    h, m = divmod(s // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s % 60:02d}s"


def load_model(device):
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import torch

    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu")
    if device != "cuda":  # checkpoints were saved on CUDA
        _load = torch.load

        def load_on_cpu(*a, **k):
            k.setdefault("map_location", torch.device("cpu"))
            return _load(*a, **k)

        torch.load = load_on_cpu
    from chatterbox.tts import ChatterboxTTS

    print(f"Loading Chatterbox on {device}...", flush=True)
    return ChatterboxTTS.from_pretrained(device=device), device


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("voice", help="reference recording of the voice (wav, 10-30 s); "
                    "with --samples, several can be given separated by commas")
    ap.add_argument("out", help="output .mp3 / .m4a / .wav")
    ap.add_argument("--pages", help='e.g. "2-66" or "5,9-12"')
    ap.add_argument("--chapter", help='only these chapters, numbered as --list-chapters shows, e.g. "3" or "3-4"')
    ap.add_argument("--expression", type=float, default=0.5, help="Chatterbox exaggeration (0.25-1.0)")
    ap.add_argument("--pace", type=float, default=0.5,
                    help="Chatterbox cfg_weight; lower is slower and more deliberate (0.2-0.7)")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--speed", type=float, default=0.85,
                    help="tempo of the finished audio, pitch unchanged (0.85 = 15%% slower; 1 = as made)")
    ap.add_argument("--passage-pause", type=float, default=0.5, help="seconds between passages")
    ap.add_argument("--para-pause", type=float, default=1.2, help="seconds after a paragraph")
    ap.add_argument("--heading-pause", type=float, default=1.5, help="seconds after a heading")
    ap.add_argument("--chapter-pause", type=float, default=4.0, help="seconds before a new lecture/chapter")
    ap.add_argument("--max-chars", type=int, default=220, help="longest passage, in characters")
    ap.add_argument("--pronunciations", help="file of 'word = say it like this' (default: pronunciations.txt)")
    ap.add_argument("--heading-regex", help="custom regex for heading lines, if the guess is wrong")
    ap.add_argument("--intro", default="", help="spoken first, e.g. a note that this is AI narration")
    ap.add_argument("--device", default="auto", help="auto, mps, cpu or cuda")
    ap.add_argument("--dry-run", action="store_true", help="print the passages; don't make audio")
    ap.add_argument("--list-chapters", action="store_true", help="print the headings found; don't make audio")
    ap.add_argument("--samples", nargs="?", const="", metavar="LETTERS",
                    help="make short samples of the first lecture in several settings to choose from "
                         "(all presets, or e.g. BDX; X = your own --expression/--pace/--speed)")
    ap.add_argument("--redo", help='remake these passages (numbers from --dry-run or the progress lines), e.g. "45,102-104"')
    ap.add_argument("--verbose", action="store_true", help="show the model's own progress bars and warnings")
    args = ap.parse_args()

    if not args.verbose:
        os.environ.setdefault("TQDM_DISABLE", "1")
        import warnings

        warnings.filterwarnings("ignore")

    pages = page_texts(args.pdf)
    wanted = parse_pages(args.pages, len(pages))
    heading_re = re.compile(args.heading_regex) if args.heading_regex else None
    blocks = structure(pages, wanted, heading_re)

    prons = [args.pronunciations] if args.pronunciations else [
        HERE / "pronunciations.txt", Path.cwd() / "pronunciations.txt"]
    rules = load_pronunciations(dict.fromkeys(str(p) for p in prons))
    items = plan(blocks, args, rules)

    if args.chapter:
        keep = parse_pages(args.chapter, 10_000)
        items = [it for it in items if it["chapter"] in keep]

    if args.list_chapters:
        heads = [it for it in items if it["heading"] and it["chapter"]]
        if not heads:
            print("No headings found. Try --heading-regex, e.g. --heading-regex '^LECTURE'")
        for it in heads:
            n = sum(1 for x in items if x["chapter"] == it["chapter"])
            print(f"{it['chapter']:>3}  p.{it['page']:<4} {it['shown']}   ({n} passages)")
        return
    if args.dry_run:
        for i, it in enumerate(items, 1):
            tag = "##" if it["heading"] else "  "
            said = "" if it["text"] == it["shown"] else f"\n        says: {it['text']}"
            print(f"[{i}] p.{it['page']} {tag} {it['shown']}{said}\n        (pause {it['pause']} s)")
        print(f"\n{len(items)} passages, {len(rules)} pronunciation rules.")
        return
    if not items:
        sys.exit("No text found on those pages.")

    out = Path(args.out)
    parts = out.with_name(out.stem + ".parts")
    parts.mkdir(parents=True, exist_ok=True)
    for i, it in enumerate(items, 1):
        it["n"] = i
    maker = Maker(args, parts)

    if args.samples is not None:
        make_samples(items, args, maker, out)
        return

    voice = args.voice.split(",")[0]
    if args.redo:
        for i in parse_pages(args.redo, len(items)):
            maker.path(items[i - 1], voice, args.expression, args.pace).unlink(missing_ok=True)
    maker.make(items, voice, args.expression, args.pace)
    join(items, maker, voice, args.expression, args.pace, args.speed, out)


PRESETS = {  # letter: (expression, pace, speed, note)
    "A": (0.5, 0.5, 1.0, "Chatterbox defaults, not slowed"),
    "B": (0.5, 0.5, 0.85, "defaults, 15% slower"),
    "C": (0.5, 0.3, 0.9, "more deliberate delivery, a little slower"),
    "D": (0.65, 0.3, 0.85, "deliberate and more expressive"),
    "E": (0.4, 0.3, 0.8, "calm, deliberate and slowest"),
}


def sample_items(items, limit_chars=650):
    """The opening of the first lecture: its heading and about 45 seconds of text."""
    first = next((i for i, it in enumerate(items) if it["heading"] and it["chapter"]), 0)
    chosen, total = [], 0
    for it in items[first:]:
        if total > limit_chars and not it["heading"]:
            break
        chosen.append(dict(it))
        total += len(it["text"])
    chosen[-1]["pause"] = 1.0
    return chosen


def make_samples(items, args, maker, out):
    letters = (args.samples or "".join(PRESETS)).upper()
    trials = [(k, *PRESETS[k]) for k in letters if k in PRESETS]
    if args.samples and "X" in letters:  # X = the settings given on the command line
        trials.append(("X", args.expression, args.pace, args.speed, "your --expression/--pace/--speed"))
    voices = args.voice.split(",")
    chosen = sample_items(items)
    folder = out.with_name(out.stem + " samples")
    folder.mkdir(exist_ok=True)
    print(f"Making {len(trials) * len(voices)} samples of {len(chosen)} passages "
          f"(the start of: {chosen[0]['shown'][:60]}).", flush=True)
    made = []
    for v in voices:
        vname = Path(v).stem
        for k, e, p, sp, note in trials:
            maker.make(chosen, v, e, p, quiet=True)
            name = f"{k} {vname} - expression {e}, pace {p}, speed {sp}{out.suffix or '.mp3'}"
            join(chosen, maker, v, e, p, sp, folder / name, quiet=True)
            made.append((k, vname, e, p, sp, note))
            print(f"  made {name}", flush=True)
    print(f"\nSamples are in: {folder}\n")
    for k, vname, e, p, sp, note in made:
        print(f"  {k}  {vname:<14} {note}")
        print(f"       --expression {e} --pace {p} --speed {sp}")
    print("\nPick one and run the book with those settings (and that voice file).\n"
          "The sample passages are reused, so they won't be made again.")


class Maker:
    """Makes passage audio, saved by voice + settings + text, loading the model only if needed."""

    def __init__(self, args, parts):
        self.args, self.parts = args, parts
        self.model = self.device = None
        self.voice_ids, self.conds_for = {}, None

    def path(self, it, voice, expression, pace):
        if voice not in self.voice_ids:
            self.voice_ids[voice] = hashlib.sha1(Path(voice).read_bytes()).hexdigest()[:12]
        key = f"{self.voice_ids[voice]}|{expression}|{pace}|{self.args.temperature}|{it['text']}"
        return self.parts / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.wav"

    def make(self, items, voice, expression, pace, quiet=False):
        todo = [it for it in items if not self.path(it, voice, expression, pace).exists()]
        if not quiet:
            print(f"{len(items)} passages; {len(items) - len(todo)} already made, {len(todo)} to make.", flush=True)
        if not todo:
            return
        if self.model is None:
            self.model, self.device = load_model(self.args.device)
        model, sr = self.model, self.model.sr
        prompt = None
        if self.conds_for != (voice, expression):
            try:
                model.prepare_conditionals(voice, exaggeration=expression)
                self.conds_for = (voice, expression)
            except Exception:
                prompt = voice
        made_audio = made_compute = 0.0
        start = time.time()
        for n, it in enumerate(todo, 1):
            t0 = time.time()
            # Speech runs at roughly 14 characters a second. Far longer means the model
            # rambled past the text; far shorter means it dropped words. Retry, keep the best.
            expect = len(it["text"]) / 14
            best = None
            for attempt in range(3):
                wav = model.generate(it["text"], audio_prompt_path=prompt, exaggeration=expression,
                                     cfg_weight=pace, temperature=self.args.temperature)
                x = level(trim_silence(wav.squeeze(0).numpy(), sr))
                secs = len(x) / sr
                off = abs(secs - expect) / max(expect, 1)
                if best is None or off < best[0]:
                    best = (off, x, secs)
                too_long = secs > 2.5 + len(it["text"]) / 6
                too_short = len(it["text"]) > 25 and secs < 0.4 * expect
                if not (too_long or too_short):
                    break
                print(f"    passage {it['n']} came out {'too long' if too_long else 'too short'} "
                      f"({secs:.0f} s for about {expect:.0f} s of text); trying again", flush=True)
            _, x, secs = best
            write_wav(self.path(it, voice, expression, pace), x, sr)
            spent = time.time() - t0
            made_audio += secs
            made_compute += spent
            per = (time.time() - start) / n
            if not quiet:
                print(f"[{n}/{len(todo)}] passage {it['n']}, p.{it['page']}  {secs:4.1f} s of audio in "
                      f"{spent:4.1f} s  · about {fmt_time(per * (len(todo) - n))} left", flush=True)
            if n == 3 and made_compute / max(made_audio, 0.1) > 8:
                print(f"    Slow: {made_compute / made_audio:.0f} s of work per second of audio. "
                      f"Close other apps, or stop (Ctrl-C) and rerun with --device "
                      f"{'cpu' if self.device != 'cpu' else 'mps'}; finished passages are kept.", flush=True)


def join(items, maker, voice, expression, pace, speed, out, quiet=False):
    import numpy as np

    if not quiet:
        print("Joining passages...", flush=True)
    chunks, sr = [], 24000
    for it in items:
        x, sr = read_wav(maker.path(it, voice, expression, pace))
        chunks.append(x)
        # Pauses are stretched by --speed later, so shrink them here to land on the stated length.
        chunks.append(np.zeros(int(it["pause"] * speed * sr), dtype="float32"))
    out = Path(out)
    joined = out.with_name(out.stem + ".joined.wav")
    write_wav(joined, np.concatenate(chunks), sr)

    if out.suffix.lower() == ".wav" and abs(speed - 1) < 1e-6:
        os.replace(joined, out)
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined)]
        if abs(speed - 1) > 1e-6:
            cmd += ["-filter:a", f"atempo={speed}"]
        if out.suffix.lower() == ".mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", "96k"]
        elif out.suffix.lower() in (".m4a", ".aac", ".mp4"):
            cmd += ["-c:a", "aac", "-b:a", "96k"]
        subprocess.run(cmd + [str(out)], check=True)
        joined.unlink()
    else:
        sys.exit(f"ffmpeg not found (brew install ffmpeg). The unslowed audio is in {joined}")

    if not quiet:
        total = sum(len(c) for c in chunks) / sr / speed
        print(f"Done: {out}  ({fmt_time(total)})")


if __name__ == "__main__":
    main()
