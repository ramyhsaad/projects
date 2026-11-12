"""
app.py: Text to Audio. Turns a PDF into an MP3 with Microsoft Edge voices.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import html
import os
import re
import threading
import time

import streamlit as st

import pdf_utils as pu
from player import AUDIO_KEY, player_html

APP_TITLE = "Text to Audio"
WORKERS = 6

VOICES = {
    "Guy": ("en-US-GuyNeural", "Warm male voice, American English."),
    "Jenny": ("en-US-JennyNeural", "Natural female voice, American English."),
    "Aria": ("en-US-AriaNeural", "Expressive female voice, American English."),
    "Ryan": ("en-GB-RyanNeural", "Calm male voice, British English."),
    "Sonia": ("en-GB-SoniaNeural", "Warm female voice, British English."),
    "William": ("en-AU-WilliamNeural", "Relaxed male voice, Australian English."),
}
PACES = {"Very slow": "-30%", "Slow": "-15%", "Normal": "+0%", "Fast": "+15%"}
DOC_KEYS = ("doc_id", "extraction", "doc_name", "page_from", "page_to", "title", "sample", "result")

st.set_page_config(page_title=APP_TITLE, page_icon="🎧", layout="centered",
                   initial_sidebar_state="collapsed")

# Local testing without the network: TTA_FAKE_TTS=1 returns tones instead of speech.
if os.environ.get("TTA_FAKE_TTS"):
    import subprocess

    def _tts(text: str, voice: str, rate: str) -> bytes:
        secs = max(0.5, len(text) / 60)
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=330:duration={secs:.2f}",
             "-ar", "24000", "-ac", "1", "-b:a", "48k", "-f", "mp3", "pipe:1"],
            capture_output=True, check=True).stdout
else:
    def _tts(text: str, voice: str, rate: str) -> bytes:
        return pu.tts_clip_edge_retry(text, voice, rate)

# ---------------------------------------------------------------------------
# Look and feel
# ---------------------------------------------------------------------------
st.markdown('<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">',
            unsafe_allow_html=True)
# st.html applies a style-only block without taking up space on the page.
st.html("""<style>
:root{--ink:#0f172a;--ink2:#475569;--muted:#64748b;--line:#e2e8f0;--green:#10b981;--green-ink:#047857;--green-soft:#ecfdf5}
html,body,.stApp,[class*="css"],button,input,textarea{font-family:'Inter',-apple-system,system-ui,sans-serif!important}
.stApp{background:#fff}
header[data-testid="stHeader"]{background:transparent;height:0}
[data-testid="stToolbar"],footer,#MainMenu,[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important}
.block-container{max-width:640px;padding:1.4rem 1.15rem 5rem}
[data-testid="stVerticalBlock"]{gap:.85rem}
.st-key-tta_head{display:none}

.brand{display:flex;align-items:center;gap:.7rem;margin:.2rem 0 .35rem}
.brand svg{flex:none}
.brand h1{font-size:1.5rem;font-weight:800;letter-spacing:-.02em;color:var(--ink);margin:0;padding:0;line-height:1.1}
.brand-sub{color:var(--ink2);font-size:.98rem;margin:0 0 .4rem}

.step{display:flex;align-items:center;gap:.6rem;margin:1rem 0 0}
.step b{flex:none;width:1.55rem;height:1.55rem;border-radius:50%;display:grid;place-items:center;font-size:.8rem;font-weight:700;color:var(--green-ink);background:var(--green-soft);border:1px solid #a7f3d0}
.step span{font-size:1.05rem;font-weight:700;color:var(--ink)}
.step.done b{background:var(--green);color:#fff;border-color:var(--green)}

[data-testid="stFileUploaderDropzone"],[data-testid="stFileUploadDropzone"]{border-radius:16px!important;border:1.5px dashed #a7f3d0!important;background:var(--green-soft)!important;padding:1.3rem 1.1rem!important}
[data-testid="stFileUploaderDropzoneInstructions"] span,[data-testid="stFileUploaderDropzoneInstructions"] small{color:var(--ink2)!important}
[data-testid="stFileUploaderDropzone"] button{border-radius:999px!important;border:1px solid var(--green)!important;color:var(--green-ink)!important;background:#fff!important;font-weight:600!important}

.doc{border:1px solid var(--line);border-radius:18px;padding:1rem 1.1rem 1.05rem;background:#fff}
.doc-title{font-weight:700;font-size:1.08rem;color:var(--ink);line-height:1.3;overflow-wrap:anywhere}
.doc-facts{color:var(--muted);font-size:.88rem;margin-top:.25rem}
.pages{display:flex;align-items:flex-end;gap:2px;height:44px;margin-top:.85rem}
.pages i{flex:1;border-radius:2px;background:#e2e8f0;min-height:3px}
.pages i.in{background:var(--green)}
.doc-note{font-size:.84rem;color:var(--muted);margin-top:.6rem}

label[data-testid="stWidgetLabel"] p{font-size:.9rem!important;font-weight:600!important;color:var(--ink)!important}
.stNumberInput input{border-radius:12px!important;font-size:1rem!important}
[data-testid="stCaptionContainer"]{color:var(--muted)!important}

.stButton>button,.stDownloadButton>button{border-radius:999px!important;min-height:3.1rem!important;font-weight:700!important;font-size:1rem!important}
.stButton>button[kind="primary"],.stDownloadButton>button[kind="primary"]{background:var(--green)!important;border:0!important;color:#fff!important;box-shadow:0 6px 18px rgba(16,185,129,.25)}
.stButton>button[kind="primary"]:hover,.stDownloadButton>button[kind="primary"]:hover{background:#059669!important}
.stButton>button[kind="primary"]:disabled{background:#a7f3d0!important;box-shadow:none}
.stButton>button[kind="secondary"]{background:#fff!important;border:1px solid var(--line)!important;color:var(--ink)!important}
.stButton>button[kind="tertiary"]{min-height:2.4rem!important;width:auto;color:var(--green-ink)!important;font-weight:600!important;padding-left:0!important}

.estimate{font-size:.92rem;color:var(--ink2);margin:.2rem 0 .1rem}
.estimate b{color:var(--ink)}
.work{background:var(--green-soft);border:1px solid #a7f3d0;border-radius:16px;padding:1rem 1.1rem}
.work-title{font-weight:700;color:var(--ink)}
.work-sub{color:var(--ink2);font-size:.9rem;margin-top:.2rem}
.stProgress>div>div>div{background:var(--green)!important}
.stAlert{border-radius:14px!important}
</style>""")



def embed(src: str, height: int, fit: bool = False) -> None:
    """Embed HTML with scripts: st.iframe on current Streamlit, components.html before it."""
    if hasattr(st, "iframe"):
        st.iframe(src, height="content" if fit else height)
    else:
        import streamlit.components.v1 as components
        components.html(src, height=height)


# Home-screen support: name, status bar and icon for Add to Home Screen.
_HEAD = """<script>
(function(){try{
  const d = window.parent.document, head = d.head;
  if (head.querySelector('meta[name="apple-mobile-web-app-title"]')) return;
  const add = (tag, attrs) => { const el = d.createElement(tag); Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v)); head.appendChild(el); };
  const url = (p) => new URL(p, window.parent.location.href).href;
  add('meta', {name: 'apple-mobile-web-app-capable', content: 'yes'});
  add('meta', {name: 'mobile-web-app-capable', content: 'yes'});
  add('meta', {name: 'apple-mobile-web-app-title', content: 'Text to Audio'});
  add('meta', {name: 'apple-mobile-web-app-status-bar-style', content: 'default'});
  add('meta', {name: 'theme-color', content: '#ffffff'});
  add('link', {rel: 'apple-touch-icon', href: url('app/static/icon-192.png')});
  add('link', {rel: 'manifest', href: url('app/static/manifest.json')});
} catch (e) {}})();
</script>"""
with st.container(key="tta_head"):
    embed(_HEAD, 1)

WAVE = """<svg width="34" height="26" viewBox="0 0 34 26" aria-hidden="true">
<rect x="0" y="10" width="4" height="6" rx="2" fill="#10b981"/><rect x="6" y="5" width="4" height="16" rx="2" fill="#10b981"/>
<rect x="12" y="0" width="4" height="26" rx="2" fill="#10b981"/><rect x="18" y="5" width="4" height="16" rx="2" fill="#10b981"/>
<rect x="24" y="8" width="4" height="10" rx="2" fill="#10b981"/><rect x="30" y="11" width="4" height="4" rx="2" fill="#10b981"/></svg>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_short(seconds: float) -> str:
    seconds = int(max(0, round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min"
    return f"{s} s"


def pages_label(a: int, b: int) -> str:
    return f"Page {a}" if a == b else f"Pages {a}–{b}"


def step(n: int, label: str, done: bool = False) -> None:
    st.markdown(f'<div class="step{" done" if done else ""}"><b>{"✓" if done else n}</b>'
                f'<span>{html.escape(label)}</span></div>', unsafe_allow_html=True)


def page_bars(chars, start: int, end: int, max_bars: int = 90) -> str:
    """One bar per page (grouped on long documents); green = will be read."""
    n = len(chars)
    if not n:
        return ""
    buckets = min(n, max_bars)
    groups = []
    for b in range(buckets):
        lo = b * n // buckets
        hi = max(lo + 1, (b + 1) * n // buckets)
        groups.append((sum(chars[lo:hi]), any(start <= p + 1 <= end for p in range(lo, hi))))
    peak = max([g[0] for g in groups] + [1])
    bars = "".join(f'<i class="{"in" if inside else ""}" style="height:{8 + 92 * (total / peak) ** 0.5:.0f}%"></i>'
                   for total, inside in groups)
    return f'<div class="pages" aria-hidden="true">{bars}</div>'


def clean_title(name: str) -> str:
    t = re.sub(r"\.pdf$", "", name, flags=re.I)
    return re.sub(r"\s+", " ", t.replace("_", " ")).strip() or "Your document"


def first_sentence(pages) -> str:
    for p in pages:
        m = re.search(r"[A-Z][^.!?]{30,170}[.!?]", pu.naturalize_for_speech(p.text or ""))
        if m:
            return m.group(0)
    return "Here is how this voice sounds reading your document."


def clear_doc() -> None:
    for k in DOC_KEYS:
        st.session_state.pop(k, None)


def start_over() -> None:
    clear_doc()
    # A new uploader key empties the file picker.
    st.session_state["upload_n"] = st.session_state.get("upload_n", 0) + 1


# ---------------------------------------------------------------------------
# Sections of the page
# ---------------------------------------------------------------------------

def header() -> None:
    st.markdown(f'<div class="brand">{WAVE}<h1>{APP_TITLE}</h1></div>'
                '<p class="brand-sub">Turn a PDF into an MP3 you can listen to anywhere.</p>',
                unsafe_allow_html=True)


def choose_document():
    done = st.session_state.get("extraction") is not None
    step(1, "Choose a PDF", done=done)
    uploaded = st.file_uploader("PDF file", type=["pdf"], label_visibility="collapsed",
                                key=f"upload_{st.session_state.get('upload_n', 0)}")
    if uploaded is None:
        if done:
            clear_doc()
        return None

    data = uploaded.getvalue()
    digest = hashlib.sha1(data).hexdigest()[:16]
    if st.session_state.get("doc_id") != digest:
        clear_doc()
        with st.spinner("Reading the PDF…"):
            result = pu.extract_pdf(data)
        st.session_state.update(doc_id=digest, extraction=result, doc_name=uploaded.name,
                                page_from=1, page_to=max(1, result.page_count))
        st.rerun()

    ex: pu.ExtractionResult = st.session_state["extraction"]
    if ex.error:
        st.error(ex.error)
        return None
    return ex


def doc_card(ex: pu.ExtractionResult) -> None:
    title = ex.title or clean_title(st.session_state["doc_name"])
    st.session_state["title"] = title
    chars = [len(p.text) for p in ex.pages]
    a, b = sorted((int(st.session_state["page_from"]), int(st.session_state["page_to"])))
    total = pu.estimate_seconds(sum(chars))
    facts = f'{ex.page_count} {"page" if ex.page_count == 1 else "pages"}, about {fmt_short(total)} of audio in all'
    note = ""
    if ex.removed_lines:
        note = (f'<div class="doc-note">Skips {ex.removed_lines} repeated headers, footers and page numbers '
                'so they aren’t read aloud.</div>')
    st.markdown(f'<div class="doc"><div class="doc-title">{html.escape(title)}</div>'
                f'<div class="doc-facts">{facts}</div>{page_bars(chars, a, b)}{note}</div>',
                unsafe_allow_html=True)
    if ex.likely_scanned:
        st.warning("Most pages in this PDF are images, so there’s little text to read. "
                   "Run it through a text recognition (OCR) app first, then upload it again.")


def choose_settings(ex: pu.ExtractionResult):
    step(2, "Pick pages and a voice")
    n = ex.page_count
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("From page", min_value=1, max_value=n, step=1, key="page_from")
    with c2:
        st.number_input("To page", min_value=1, max_value=n, step=1, key="page_to")
    a, b = sorted((int(st.session_state["page_from"]), int(st.session_state["page_to"])))

    voice = st.pills("Voice", list(VOICES), default="Guy", key="voice", selection_mode="single") or "Guy"
    st.caption(VOICES[voice][1])
    if st.button(f"Hear {voice}", type="tertiary", key="sample_btn", icon=":material/play_circle:"):
        try:
            with st.spinner("Getting a sample…"):
                st.session_state["sample"] = (voice, _tts(f"This is {voice}. {first_sentence(ex.pages)}",
                                                          VOICES[voice][0], "+0%"))
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("sample", None)
            st.error(f"The voice sample didn’t load. Try again in a moment. ({e})")
    sample = st.session_state.get("sample")
    if sample and sample[0] == voice:
        st.audio(sample[1], format="audio/mpeg", autoplay=True)

    pace = st.segmented_control("Reading pace", list(PACES), default="Normal", key="pace") or "Normal"
    st.caption("You can also change the speed while listening.")

    chars = sum(len(p.text) for p in ex.pages[a - 1:b])
    secs = pu.estimate_seconds(chars, PACES[pace])
    if chars:
        st.markdown(f'<p class="estimate"><b>{pages_label(a, b)}</b>: about {fmt_short(secs)} of audio. '
                    f'Making the MP3 takes about {fmt_short(max(10, secs / 40))}.</p>', unsafe_allow_html=True)
    else:
        st.warning(f"{pages_label(a, b)} {'has' if a == b else 'have'} no text to read. Choose different pages.")
    clicked = st.button("Make MP3", type="primary", disabled=not chars, key="make",
                        icon=":material/graphic_eq:", width="stretch")
    return clicked, a, b, voice, pace


def make_audio(ex: pu.ExtractionResult, a: int, b: int, voice: str, pace: str) -> None:
    parts = pu.build_parts(ex.pages[a - 1:b])
    if not parts:
        st.warning(f"{pages_label(a, b)} {'has' if a == b else 'have'} no text to read.")
        return
    st.session_state.pop("result", None)
    n = len(parts)
    results = [None] * n
    errors = []
    done = [0]
    lock = threading.Lock()
    started = time.time()
    status = st.empty()
    bar = st.progress(0.0)

    def render(k: int) -> None:
        elapsed = time.time() - started
        eta = "Working out how long this takes."
        if k and elapsed > 1:
            left = (n - k) * elapsed / k
            eta = "Almost done." if left < 5 else f"About {fmt_short(left)} left."
        status.markdown(
            f'<div class="work"><div class="work-title">Making your MP3: {int(100 * k / n)}%</div>'
            f'<div class="work-sub">Part {k} of {n}. {eta} Keep this page open until it finishes.</div></div>',
            unsafe_allow_html=True)

    def work(i: int, text: str) -> None:
        audio = _tts(text, VOICES[voice][0], PACES[pace])
        with lock:
            results[i] = audio
            done[0] += 1

    render(0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(work, i, p.text): i for i, p in enumerate(parts)}
        for f in concurrent.futures.as_completed(futures):
            if f.exception():
                errors.append(futures[f])
            render(done[0])
            bar.progress(done[0] / n)
    bar.empty()
    status.empty()

    if errors:
        missing = ", ".join(pages_label(parts[i].page_start, parts[i].page_end) for i in sorted(errors)[:4])
        st.error(f"The voice service didn’t answer for {len(errors)} of {n} parts ({missing}), so no MP3 "
                 "was made. Tap Make MP3 to try again.")
        return

    sections, t = [], 0.0
    for p, audio in zip(parts, results):
        sections.append((pages_label(p.page_start, p.page_end), t))
        t += pu.mp3_duration(audio)
    st.session_state["result"] = {
        "audio": b"".join(results),
        "sections": sections,
        "duration": t,
        "pages": (a, b),
        "voice": voice,
        "id": f'{st.session_state["doc_id"]}-{a}-{b}-{voice}-{pace}',
    }


def listen() -> None:
    r = st.session_state.get("result")
    if not r:
        return
    title = st.session_state.get("title", "Audio")
    a, b = r["pages"]
    step(3, "Listen or download")
    meta = f"{pages_label(a, b)}, read by {r['voice']}, {fmt_short(r['duration'])}"
    embed(player_html(doc_id=r["id"], title=title, meta=meta,
                      sections=r["sections"], duration=r["duration"]), 336, fit=True)
    with st.container(key=AUDIO_KEY):
        st.audio(r["audio"], format="audio/mpeg")
    safe = re.sub(r"[^\w\- ]+", "", title).strip().replace(" ", "_")[:80] or "audio"
    st.download_button(f"Download MP3 ({len(r['audio']) / 1048576:.1f} MB)", data=r["audio"],
                       file_name=f"{safe}.mp3", mime="audio/mpeg", type="primary",
                       icon=":material/download:", key="download", on_click="ignore",
                       width="stretch")
    st.caption("On iPhone, the MP3 is saved to Downloads in the Files app.")


def main() -> None:
    header()
    ex = choose_document()
    if not ex:
        return
    doc_card(ex)
    clicked, a, b, voice, pace = choose_settings(ex)
    if clicked:
        make_audio(ex, a, b, voice, pace)
    listen()
    if st.session_state.get("result"):
        if st.button("Start over with another PDF", type="secondary", key="restart", width="stretch"):
            start_over()
            st.rerun()


main()
