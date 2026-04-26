"""
app.py — long-pdf-reader
"""
from __future__ import annotations

import base64
import os
import time
from typing import Optional

import streamlit as st

import pdf_utils as pu

APP_TITLE = "Long PDF Reader"

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📖",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
      /* ── Typography & spacing ── */
      .block-container {
          padding-top: 1.5rem;
          padding-bottom: 6rem;
          max-width: 680px;
      }

      /* ── App header ── */
      .pdf-header {
          text-align: center;
          padding: 1.6rem 1rem 1rem;
          margin-bottom: 0.5rem;
      }
      .pdf-header .icon { font-size: 2.8rem; line-height: 1; margin-bottom: 0.3rem; }
      .pdf-header h1 {
          font-size: 1.7rem;
          font-weight: 700;
          margin: 0 0 0.2rem;
          letter-spacing: -0.5px;
      }
      .pdf-header p {
          font-size: 0.9rem;
          opacity: 0.55;
          margin: 0;
      }

      /* ── Section cards ── */
      .card {
          border: 1px solid rgba(128,128,128,0.2);
          border-radius: 16px;
          padding: 1.2rem 1.3rem 1.1rem;
          margin-bottom: 1.1rem;
          background: rgba(128,128,128,0.04);
      }
      .card-title {
          font-size: 0.72rem;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          opacity: 0.45;
          margin: 0 0 0.75rem;
      }

      /* ── Buttons ── */
      .stButton > button, .stDownloadButton > button {
          width: 100%;
          padding: 0.8rem 1rem;
          font-size: 1rem;
          font-weight: 600;
          border-radius: 12px;
          min-height: 48px;
          letter-spacing: 0.01em;
          transition: opacity 0.15s;
      }
      .stButton > button:hover { opacity: 0.88; }

      /* ── Form controls ── */
      .stTextInput input,
      .stTextArea textarea,
      .stNumberInput input,
      .stSelectbox div[data-baseweb="select"] {
          font-size: 1rem !important;
          border-radius: 10px !important;
      }

      /* ── File uploader ── */
      [data-testid="stFileUploadDropzone"] {
          border-radius: 14px;
          border: 2px dashed rgba(128,128,128,0.3) !important;
          padding: 1.4rem;
          background: rgba(128,128,128,0.03);
      }

      /* ── Audio player wrapper ── */
      .player-card {
          border: 1px solid rgba(128,128,128,0.2);
          border-radius: 18px;
          padding: 1.2rem 1.3rem;
          margin-bottom: 1rem;
          background: rgba(99,102,241,0.06);
      }
      .player-meta {
          font-size: 0.82rem;
          opacity: 0.5;
          margin-bottom: 0.6rem;
          display: flex;
          gap: 0.8rem;
          align-items: center;
      }
      .player-dot { opacity: 0.3; }

      /* ── Misc ── */
      h2, h3 { margin-top: 0.4rem !important; font-weight: 700; }
      details summary { font-size: 0.95rem; }
      .stAlert { border-radius: 12px !important; }
      [data-testid="stStatusWidget"] { border-radius: 12px; }
      footer { display: none; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

def _get_secret(name: str) -> Optional[str]:
    try:
        val = st.secrets.get(name)  # type: ignore[attr-defined]
    except Exception:
        val = None
    if val:
        return str(val).strip()
    val = os.environ.get(name)
    return val.strip() if val else None


APP_PASSWORD = _get_secret("APP_PASSWORD")
OPENAI_API_KEY = _get_secret("OPENAI_API_KEY")


def password_gate() -> bool:
    """Password gate — currently disabled for personal use."""
    return True


# ---------------------------------------------------------------------------
# OpenAI client (lazy, cached)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_openai_client():
    if not OPENAI_API_KEY:
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        st.error(f"Could not initialize OpenAI client: {e}")
        return None


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def init_state():
    ss = st.session_state
    defaults = {
        "_unlocked": False,
        "doc_name": None,
        "doc_size_mb": 0.0,
        "extraction": None,
        "chunks": None,
        "index_built": False,
        "full_audio": None,
        "last_answer": None,
        "last_summary": None,
    }
    for k, v in defaults.items():
        ss.setdefault(k, v)


def reset_document_state():
    keep = {"_unlocked"}
    for k in list(st.session_state.keys()):
        if k not in keep:
            del st.session_state[k]
    init_state()


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def section_upload():
    st.markdown('<div class="card-title">Upload</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "Choose a PDF",
        type=["pdf"],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )
    if uploaded is None:
        return

    size_mb = uploaded.size / (1024 * 1024)
    if size_mb > pu.MAX_UPLOAD_MB:
        st.error(
            f"This file is {size_mb:.1f} MB — above the {pu.MAX_UPLOAD_MB} MB limit."
        )
        return

    if (st.session_state.get("doc_name") != uploaded.name
            or st.session_state.get("extraction") is None):
        reset_document_state()
        st.session_state["doc_name"] = uploaded.name
        st.session_state["doc_size_mb"] = size_mb

        with st.status("Reading PDF…", expanded=False) as status:
            try:
                pdf_bytes = uploaded.getvalue()
                result = pu.extract_pdf(pdf_bytes)
            except Exception as e:
                status.update(label="Failed to read PDF", state="error")
                st.error(f"Unexpected error: {e}")
                return
            st.session_state["extraction"] = result
            status.update(label="PDF read", state="complete")

    extraction: pu.ExtractionResult = st.session_state["extraction"]
    if extraction.error:
        st.error(extraction.error)
        return

    n_pages = extraction.page_count
    pages_with_text = sum(1 for p in extraction.pages if (p.text or "").strip())
    st.success(
        f"**{uploaded.name}** · {n_pages} pages · {size_mb:.1f} MB"
    )

    if extraction.likely_scanned:
        st.warning(
            "This PDF looks scanned or image-only — minimal text extracted. "
            "Run OCR first (e.g. `ocrmypdf input.pdf output.pdf`) and re-upload."
        )

    with st.expander("Preview a page"):
        page_options = [p.page_number for p in extraction.pages]
        if page_options:
            chosen = st.selectbox("Page", page_options, key="preview_page")
            text = next((p.text for p in extraction.pages
                         if p.page_number == chosen), "")
            st.text_area("Extracted text",
                         text or "(no extractable text on this page)",
                         height=200)


def section_build_index():
    extraction: Optional[pu.ExtractionResult] = st.session_state.get("extraction")
    if not extraction or extraction.error or not extraction.pages:
        return

    st.markdown('<div class="card-title" style="margin-top:1rem">Search index</div>',
                unsafe_allow_html=True)

    if st.session_state.get("index_built"):
        n_chunks = len(st.session_state.get("chunks") or [])
        st.success(f"Index ready — {n_chunks} chunks embedded.")
        if st.button("Rebuild index", type="secondary"):
            st.session_state["index_built"] = False
            st.session_state["chunks"] = None
            st.rerun()
        return

    client = get_openai_client()
    if client is None:
        st.info("Add `OPENAI_API_KEY` to secrets to enable search & summarization.")
        return

    chunks_preview = pu.chunk_pages(extraction.pages)
    if not chunks_preview:
        st.warning("No text could be chunked from this PDF.")
        return

    total_chars = sum(len(c.text) for c in chunks_preview)
    st.caption(f"{len(chunks_preview)} chunks · ~{total_chars:,} characters")

    if st.button("Build search index", type="primary"):
        progress = st.progress(0.0, text="Embedding chunks…")
        try:
            def cb(done, total):
                progress.progress(min(done / max(total, 1), 1.0),
                                  text=f"Embedded {done}/{total}")
            embeddings = pu.embed_texts(client, [c.text for c in chunks_preview],
                                        progress_cb=cb)
        except pu.OpenAICallError as e:
            progress.empty()
            st.error(e.user_message)
            return
        except Exception as e:
            progress.empty()
            st.error(f"Unexpected error: {e}")
            return

        for c, emb in zip(chunks_preview, embeddings):
            c.embedding = emb
        st.session_state["chunks"] = chunks_preview
        st.session_state["index_built"] = True
        progress.empty()
        st.rerun()


def section_ask():
    if not st.session_state.get("index_built"):
        return

    st.markdown('<div class="card-title" style="margin-top:1rem">Ask a question</div>',
                unsafe_allow_html=True)

    question = st.text_area(
        "Your question",
        placeholder="What does the author say about…",
        height=100,
        key="question_input",
    )
    k = st.slider("Excerpts to consult", min_value=2,
                  max_value=pu.MAX_RETRIEVED_CHUNKS,
                  value=min(6, pu.MAX_RETRIEVED_CHUNKS))

    if st.button("Ask", type="primary"):
        client = get_openai_client()
        if client is None:
            st.error("OpenAI key is missing.")
            return
        if not question.strip():
            st.warning("Please enter a question.")
            return
        with st.spinner("Searching…"):
            try:
                q_emb = pu.embed_texts(client, [question])[0]
                top = pu.top_k_chunks(q_emb, st.session_state["chunks"], k=k)
                answer = pu.answer_with_citations(client, question, top)
            except pu.OpenAICallError as e:
                st.error(e.user_message)
                return
            except Exception as e:
                st.error(f"Unexpected error: {e}")
                return
        st.session_state["last_answer"] = (question, answer, top)

    last = st.session_state.get("last_answer")
    if last:
        q, a, top = last
        st.markdown(f"**Q:** {q}")
        st.markdown(a)
        with st.expander("Source excerpts"):
            for score, c in top:
                st.markdown(f"**{pu.chunk_label(c).capitalize()}** — {score:.2f}")
                st.write(c.text)
                st.divider()


def section_summarize():
    extraction: Optional[pu.ExtractionResult] = st.session_state.get("extraction")
    chunks = st.session_state.get("chunks")
    if not extraction or not extraction.pages or not chunks:
        return

    st.markdown('<div class="card-title" style="margin-top:1rem">Summarize</div>',
                unsafe_allow_html=True)

    n = extraction.page_count
    col1, col2 = st.columns(2)
    with col1:
        start_page = st.number_input("Start page", min_value=1, max_value=n,
                                     value=1, step=1)
    with col2:
        end_page = st.number_input("End page", min_value=1, max_value=n,
                                   value=min(n, int(start_page) + 9), step=1)

    style = st.selectbox("Style", [
        "Short executive summary with key takeaways",
        "Detailed study notes with headings",
        "Chapter-style outline",
        "Action items, decisions, and risks",
        "Plain-English explanation",
    ])

    span = int(end_page) - int(start_page) + 1
    gen_disabled = span <= 0 or span > pu.MAX_SUMMARY_PAGES

    if span > pu.MAX_SUMMARY_PAGES:
        st.warning(f"Limit is {pu.MAX_SUMMARY_PAGES} pages per run.")

    if st.button("Summarize", type="primary", disabled=gen_disabled):
        client = get_openai_client()
        if client is None:
            st.error("OpenAI key is missing.")
            return
        selected = pu.select_chunks_in_range(
            chunks, int(start_page), int(end_page),
            max_chunks=pu.MAX_SUMMARY_CHUNKS,
        )
        if not selected:
            st.warning("No extractable text in that range.")
            return

        progress = st.progress(0.0, text="Summarizing…")
        try:
            batch_size = 6
            partials = []
            total = len(selected)
            for i in range(0, total, batch_size):
                batch = selected[i:i + batch_size]
                partials.append(pu.summarize_chunks(client, batch, style))
                done = min(i + len(batch), total)
                progress.progress(done / total, text=f"Summarized {done}/{total}")
            final = (pu.reduce_summaries(client, partials, style)
                     if len(partials) > 1 else partials[0])
        except pu.OpenAICallError as e:
            progress.empty()
            st.error(e.user_message)
            return
        except Exception as e:
            progress.empty()
            st.error(f"Unexpected error: {e}")
            return
        progress.empty()
        st.session_state["last_summary"] = (int(start_page), int(end_page), final)

    last = st.session_state.get("last_summary")
    if last:
        s, e, summary = last
        st.markdown(f"**Pages {s}–{e}:**")
        st.markdown(summary)
        st.download_button(
            "Download summary",
            data=summary.encode("utf-8"),
            file_name=f"summary_p{s}-p{e}.txt",
            mime="text/plain",
        )


def section_audio():
    extraction: Optional[pu.ExtractionResult] = st.session_state.get("extraction")
    if not extraction or not extraction.pages:
        return

    st.markdown('<div class="card-title" style="margin-top:1rem">Listen</div>',
                unsafe_allow_html=True)

    n = extraction.page_count
    col1, col2 = st.columns(2)
    with col1:
        a_start = st.number_input("From page", min_value=1, max_value=n,
                                  value=1, step=1, key="audio_start")
    with col2:
        a_end = st.number_input("To page", min_value=1, max_value=n,
                                value=n, step=1, key="audio_end")

    col3, col4 = st.columns(2)
    with col3:
        voice_label = st.selectbox("Voice", list(pu.EDGE_TTS_VOICES.keys()), index=0)
    with col4:
        rate_label = st.selectbox("Speed", list(pu.EDGE_TTS_RATES.keys()), index=0)

    edge_voice = pu.EDGE_TTS_VOICES[voice_label]
    edge_rate = pu.EDGE_TTS_RATES[rate_label]

    span = int(a_end) - int(a_start) + 1
    gen_disabled = span <= 0 or span > pu.MAX_AUDIO_PAGES

    if span > pu.MAX_AUDIO_PAGES:
        st.warning(f"Limit is {pu.MAX_AUDIO_PAGES} pages per run.")
    elif span > 0:
        st.caption(f"{span} page(s) · free Microsoft neural TTS · no API key needed")

    if st.button("Generate audio", type="primary", disabled=gen_disabled):
        raw = pu.get_pages_text(extraction.pages, int(a_start), int(a_end))
        if not raw.strip():
            st.warning("No extractable text in the selected pages.")
            return

        clips_text = pu.split_for_tts(raw)
        total_clips = len(clips_text)
        st.session_state["full_audio"] = None

        progress = st.progress(0.0, text=f"Generating audio ({total_clips} clips)…")

        import concurrent.futures
        import threading
        results = [None] * total_clips
        completed = [0]
        lock = threading.Lock()

        def _gen(idx, text):
            audio = pu.tts_clip_edge(text, voice=edge_voice, rate=edge_rate)
            with lock:
                results[idx] = audio
                completed[0] += 1
                progress.progress(
                    completed[0] / total_clips,
                    text=f"Generated {completed[0]} of {total_clips}…"
                )

        errors = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(_gen, i, ct): i
                       for i, ct in enumerate(clips_text)}
            for fut in concurrent.futures.as_completed(futures):
                exc = fut.exception()
                if exc:
                    errors.append(str(exc))

        progress.empty()
        good = [b for b in results if b]
        if good:
            st.session_state["full_audio"] = b"".join(good)
        if errors:
            st.warning(f"{len(errors)} clip(s) had errors and were skipped.")

    full_audio = st.session_state.get("full_audio")
    if full_audio:
        doc_name = st.session_state.get("doc_name", "audio")
        safe_name = doc_name.lower().replace(" ", "_").replace("/", "_").replace(".pdf", "")
        size_mb = len(full_audio) / (1024 * 1024)
        title_js = doc_name.replace(".pdf", "").replace("'", "\\'")

        b64 = base64.b64encode(full_audio).decode()
        player_html = f"""
<style>
  #pdfplayer {{
    width: 100%;
    border-radius: 10px;
    outline: none;
    accent-color: #6366f1;
    margin: 0;
  }}
</style>
<audio id="pdfplayer" controls preload="auto">
  <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
</audio>
<script>
(function() {{
  const a = document.getElementById('pdfplayer');
  if (!('mediaSession' in navigator)) return;
  navigator.mediaSession.metadata = new MediaMetadata({{
    title: '{title_js}',
    artist: 'Long PDF Reader',
    album: 'Pages {int(a_start)}–{int(a_end)}',
  }});
  const upd = () => {{
    if (a.duration) navigator.mediaSession.setPositionState({{
      duration: a.duration, playbackRate: a.playbackRate, position: a.currentTime
    }});
  }};
  a.addEventListener('play',  () => {{ navigator.mediaSession.playbackState = 'playing'; }});
  a.addEventListener('pause', () => {{ navigator.mediaSession.playbackState = 'paused'; }});
  a.addEventListener('timeupdate', upd);
  navigator.mediaSession.setActionHandler('play',  () => a.play());
  navigator.mediaSession.setActionHandler('pause', () => a.pause());
  navigator.mediaSession.setActionHandler('seekforward',  d => {{
    a.currentTime = Math.min(a.currentTime + (d.seekOffset || 30), a.duration);
  }});
  navigator.mediaSession.setActionHandler('seekbackward', d => {{
    a.currentTime = Math.max(a.currentTime - (d.seekOffset || 30), 0);
  }});
}})();
</script>
"""
        st.markdown(
            f'<div class="player-meta">'
            f'<span>🎧 {title_js}</span>'
            f'<span class="player-dot">·</span>'
            f'<span>Pages {int(a_start)}–{int(a_end)}</span>'
            f'<span class="player-dot">·</span>'
            f'<span>{size_mb:.1f} MB</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.components.v1.html(player_html, height=60)
        st.download_button(
            "⬇  Download MP3",
            data=full_audio,
            file_name=f"{safe_name}.mp3",
            mime="audio/mpeg",
            key="dl_full",
        )


def section_reset():
    if st.session_state.get("doc_name"):
        st.divider()
        if st.button("Start over with a new PDF", type="secondary"):
            reset_document_state()
            st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    init_state()
    if not password_gate():
        return

    # Header
    st.markdown(
        """
        <div class="pdf-header">
          <div class="icon">📖</div>
          <h1>Long PDF Reader</h1>
          <p>Upload · Listen · Ask · Summarize</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    section_upload()
    section_build_index()
    section_ask()
    section_summarize()
    section_audio()
    section_reset()


if __name__ == "__main__":
    main()
