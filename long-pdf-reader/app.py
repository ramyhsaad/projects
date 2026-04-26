"""
app.py — long-pdf-reader

Private Streamlit app for reading and querying long PDFs from a phone.

Step sequence:
    1. Upload PDF
    2. Read pages
    3. Build search index
    4. Ask / Summarize / Listen
"""
from __future__ import annotations

import os
import time
from typing import Optional

import streamlit as st

import pdf_utils as pu

APP_TITLE = "Long PDF Reader"

# ---------------------------------------------------------------------------
# Page config + mobile-friendly CSS
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="📖",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      /* Bigger, thumb-friendly tap targets */
      .stButton > button, .stDownloadButton > button {
          width: 100%;
          padding: 0.85rem 1rem;
          font-size: 1.05rem;
          border-radius: 12px;
          min-height: 48px;
      }
      .stTextInput input, .stTextArea textarea, .stNumberInput input,
      .stSelectbox div[data-baseweb="select"] {
          font-size: 1.05rem !important;
      }
      .block-container { padding-top: 1.2rem; padding-bottom: 5rem; }
      details summary { font-size: 1.0rem; }
      [data-testid="stFileUploadDropzone"] { padding: 1.2rem; }
      /* Section headers smaller on mobile so they don't dominate */
      h2, h3 { margin-top: 0.6rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Secrets / password gate
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
    """Show password prompt. Returns True if unlocked."""
    if not APP_PASSWORD:
        st.warning(
            "⚠️ No `APP_PASSWORD` is configured. The app is running without "
            "a password gate. Set `APP_PASSWORD` in your Streamlit secrets "
            "to enable private access."
        )
        return True
    if st.session_state.get("_unlocked"):
        return True

    st.title(f"📖 {APP_TITLE}")
    st.write("This app is private. Enter the password to continue.")
    pw = st.text_input("Password", type="password",
                       label_visibility="collapsed",
                       placeholder="Password",
                       key="_pw_input")
    if st.button("Unlock", type="primary"):
        if pw == APP_PASSWORD:
            st.session_state["_unlocked"] = True
            st.rerun()
        else:
            time.sleep(0.6)  # mild brute-force speed bump
            st.error("Incorrect password.")
    return False


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
        "extraction": None,         # pu.ExtractionResult
        "chunks": None,             # List[pu.TextChunk]
        "index_built": False,
        "audio_clips": [],          # list of (label, bytes)
        "last_answer": None,        # (question, answer, retrieved)
        "last_summary": None,       # (start, end, text)
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

def section_privacy():
    with st.expander("🔒 Privacy & limits", expanded=False):
        st.markdown(
            f"""
- This app sends **excerpts of your PDF** to OpenAI to generate
  embeddings, answer questions, write summaries, and produce audio.
- The app **does not intentionally save your PDFs**. They live only in
  memory for the current browser session and are dropped on reload.
- Your password is checked locally against the `APP_PASSWORD` secret;
  it is never sent to OpenAI.
- Hard limits in this build:
  - Max upload: **{pu.MAX_UPLOAD_MB} MB**
  - Max summary span: **{pu.MAX_SUMMARY_PAGES} pages** /
    **{pu.MAX_SUMMARY_CHUNKS} chunks**
  - Max audio span: **{pu.MAX_AUDIO_PAGES} pages**, up to
    **{pu.MAX_AUDIO_CLIPS_PER_RUN} clips per run**
  - Q&A retrieves up to **{pu.MAX_RETRIEVED_CHUNKS} excerpts**
            """
        )


def section_upload():
    st.subheader("1) Upload PDF")
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
            f"This file is {size_mb:.1f} MB, larger than the "
            f"{pu.MAX_UPLOAD_MB} MB limit. Please upload a smaller PDF."
        )
        return

    # Only re-process if it's a different file
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
                st.error(f"Unexpected error reading the PDF: {e}")
                return
            st.session_state["extraction"] = result
            status.update(label="PDF read", state="complete")

    extraction: pu.ExtractionResult = st.session_state["extraction"]
    if extraction.error:
        st.error(extraction.error)
        return

    n_pages = extraction.page_count
    pages_with_text = sum(1 for p in extraction.pages
                          if (p.text or "").strip())
    st.success(
        f"Loaded **{uploaded.name}** — {n_pages} pages "
        f"({pages_with_text} with text), {size_mb:.1f} MB."
    )

    if extraction.likely_scanned:
        st.warning(
            "This PDF looks **scanned or image-only** — very little text "
            "could be extracted. This app does not run OCR. To use it:\n\n"
            "1. Open the PDF on your computer.\n"
            "2. Run OCR (Adobe Acrobat → *Recognize Text*, or the free "
            "`ocrmypdf` tool: `ocrmypdf input.pdf output.pdf`).\n"
            "3. Re-upload the OCR'd version."
        )

    # Optional: peek at a single page
    with st.expander("Preview a page"):
        page_options = [p.page_number for p in extraction.pages]
        if page_options:
            chosen = st.selectbox("Page", page_options, key="preview_page")
            text = next((p.text for p in extraction.pages
                         if p.page_number == chosen), "")
            st.text_area("Extracted text",
                         text or "(no extractable text on this page)",
                         height=240)


def section_build_index():
    extraction: Optional[pu.ExtractionResult] = st.session_state.get("extraction")
    if not extraction or extraction.error or not extraction.pages:
        return

    st.subheader("2) Build search index")
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
        st.error("OpenAI key is missing. Add `OPENAI_API_KEY` to secrets.")
        return

    chunks_preview = pu.chunk_pages(extraction.pages)
    if not chunks_preview:
        st.warning(
            "No text could be chunked from this PDF. If it's scanned, "
            "run OCR first (see message above).")
        return

    total_chars = sum(len(c.text) for c in chunks_preview)
    st.caption(
        f"Will embed **{len(chunks_preview)} chunks** "
        f"(~{total_chars:,} characters). This is the most expensive step "
        "— small PDFs cost a fraction of a cent."
    )
    if st.button("Build index", type="primary"):
        progress = st.progress(0.0, text="Embedding chunks…")
        try:
            def cb(done, total):
                progress.progress(min(done / max(total, 1), 1.0),
                                  text=f"Embedded {done}/{total} chunks")
            embeddings = pu.embed_texts(
                client,
                [c.text for c in chunks_preview],
                progress_cb=cb,
            )
        except pu.OpenAICallError as e:
            progress.empty()
            st.error(e.user_message)
            return
        except Exception as e:
            progress.empty()
            st.error(f"Unexpected error while building the index: {e}")
            return

        for c, emb in zip(chunks_preview, embeddings):
            c.embedding = emb
        st.session_state["chunks"] = chunks_preview
        st.session_state["index_built"] = True
        progress.empty()
        st.success(f"Index built — {len(chunks_preview)} chunks ready.")
        st.rerun()


def section_ask():
    if not st.session_state.get("index_built"):
        return
    st.subheader("3) Ask a question")

    question = st.text_area(
        "Your question",
        placeholder="e.g. What does the author say about climate adaptation?",
        height=110,
        key="question_input",
    )
    k = st.slider("How many excerpts to consult", min_value=2,
                  max_value=pu.MAX_RETRIEVED_CHUNKS,
                  value=min(6, pu.MAX_RETRIEVED_CHUNKS))

    if st.button("Ask", type="primary"):
        client = get_openai_client()
        if client is None:
            st.error("OpenAI key is missing.")
            return
        if not question.strip():
            st.warning("Please type a question first.")
            return
        with st.spinner("Searching the document…"):
            try:
                q_emb = pu.embed_texts(client, [question])[0]
                top = pu.top_k_chunks(q_emb, st.session_state["chunks"], k=k)
                answer = pu.answer_with_citations(client, question, top)
            except pu.OpenAICallError as e:
                st.error(e.user_message)
                return
            except Exception as e:
                st.error(f"Unexpected error while answering: {e}")
                return
        st.session_state["last_answer"] = (question, answer, top)

    last = st.session_state.get("last_answer")
    if last:
        q, a, top = last
        st.markdown(f"**Q:** {q}")
        st.markdown(a)
        with st.expander("Show source excerpts"):
            for score, c in top:
                st.markdown(f"**{pu.chunk_label(c).capitalize()}** — relevance {score:.2f}")
                st.write(c.text)
                st.divider()


def section_summarize():
    extraction: Optional[pu.ExtractionResult] = st.session_state.get("extraction")
    chunks = st.session_state.get("chunks")
    if not extraction or not extraction.pages or not chunks:
        return
    st.subheader("4) Summarize a page range")

    n = extraction.page_count
    col1, col2 = st.columns(2)
    with col1:
        start_page = st.number_input("Start page", min_value=1,
                                     max_value=n, value=1, step=1)
    with col2:
        default_end = min(n, int(start_page) + 9)
        end_page = st.number_input("End page", min_value=1, max_value=n,
                                   value=default_end, step=1)

    style = st.selectbox(
        "Summary style",
        [
            "Short executive summary with key takeaways",
            "Detailed study notes with headings",
            "Chapter-style outline",
            "Action items, decisions, and risks",
            "Plain-English explanation",
        ],
    )

    span = int(end_page) - int(start_page) + 1
    if span <= 0:
        st.warning("End page must be ≥ start page.")
        return
    if span > pu.MAX_SUMMARY_PAGES:
        st.warning(
            f"Range is {span} pages. Limit per summary is "
            f"{pu.MAX_SUMMARY_PAGES} pages — please narrow the range.")
        gen_disabled = True
    else:
        st.caption(f"Will summarize **{span} page(s)**. "
                   "Longer ranges cost more.")
        gen_disabled = False

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
            st.warning("No extractable text found in that page range.")
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
                progress.progress(done / total,
                                  text=f"Summarized {done}/{total} chunks")
            final = pu.reduce_summaries(client, partials, style) \
                if len(partials) > 1 else partials[0]
        except pu.OpenAICallError as e:
            progress.empty()
            st.error(e.user_message)
            return
        except Exception as e:
            progress.empty()
            st.error(f"Unexpected error while summarizing: {e}")
            return
        progress.empty()
        st.session_state["last_summary"] = (int(start_page), int(end_page), final)

    last = st.session_state.get("last_summary")
    if last:
        s, e, summary = last
        st.markdown(f"**Summary of pages {s}–{e}:**")
        st.markdown(summary)
        st.download_button(
            "Download summary (.txt)",
            data=summary.encode("utf-8"),
            file_name=f"summary_p{s}-p{e}.txt",
            mime="text/plain",
        )


def section_audio():
    extraction: Optional[pu.ExtractionResult] = st.session_state.get("extraction")
    if not extraction or not extraction.pages:
        return
    st.subheader("5) Listen — generate audio")

    n = extraction.page_count
    col1, col2 = st.columns(2)
    with col1:
        a_start = st.number_input("From page", min_value=1, max_value=n,
                                  value=1, step=1, key="audio_start")
    with col2:
        default_end = min(n, int(a_start) + 2)
        a_end = st.number_input("To page", min_value=1, max_value=n,
                                value=default_end, step=1, key="audio_end")

    voice = st.selectbox(
        "Voice",
        ["alloy", "verse", "ash", "sage", "coral", "ballad", "echo", "shimmer"],
        index=0,
    )
    style_label = st.selectbox("Reading style", list(pu.VOICE_STYLES.keys()),
                               index=0)
    instructions = pu.VOICE_STYLES[style_label]

    span = int(a_end) - int(a_start) + 1
    if span <= 0:
        st.warning("End page must be ≥ start page.")
        return
    if span > pu.MAX_AUDIO_PAGES:
        st.warning(
            f"Audio range is {span} pages. Limit is {pu.MAX_AUDIO_PAGES} "
            f"pages per run — please narrow the range.")
        gen_disabled = True
    else:
        st.caption(
            f"Will read **{span} page(s)** aloud, split into up to "
            f"{pu.MAX_AUDIO_CLIPS_PER_RUN} clips. Audio generation is the "
            "slowest step (≈ 10–30 sec per clip).")
        gen_disabled = False

    if st.button("Generate audio", type="primary", disabled=gen_disabled):
        client = get_openai_client()
        if client is None:
            st.error("OpenAI key is missing.")
            return

        raw = pu.get_pages_text(extraction.pages, int(a_start), int(a_end))
        if not raw.strip():
            st.warning("The selected pages contain no extractable text.")
            return

        clips_text = pu.split_for_tts(raw)
        if len(clips_text) > pu.MAX_AUDIO_CLIPS_PER_RUN:
            st.info(
                f"Selection produced {len(clips_text)} clips; capping at "
                f"{pu.MAX_AUDIO_CLIPS_PER_RUN}. Narrow the range to cover "
                "the rest in a follow-up run.")
            clips_text = clips_text[:pu.MAX_AUDIO_CLIPS_PER_RUN]

        st.session_state["audio_clips"] = []
        progress = st.progress(0.0, text="Generating audio…")
        for i, ct in enumerate(clips_text, start=1):
            try:
                audio_bytes = pu.tts_clip(
                    client, ct, voice=voice, instructions=instructions)
            except pu.OpenAICallError as e:
                progress.empty()
                st.error(f"Clip {i} failed: {e.user_message}")
                break  # keep prior clips — partial success is fine
            except Exception as e:
                progress.empty()
                st.error(f"Clip {i} failed unexpectedly: {e}")
                break
            label = f"Clip {i} of {len(clips_text)}"
            st.session_state["audio_clips"].append((label, audio_bytes))
            progress.progress(i / len(clips_text),
                              text=f"Generated {i}/{len(clips_text)} clips")
        progress.empty()
        if st.session_state["audio_clips"]:
            st.success(
                f"Generated {len(st.session_state['audio_clips'])} clip(s).")

    clips = st.session_state.get("audio_clips") or []
    for label, audio_bytes in clips:
        st.markdown(f"**{label}**")
        st.audio(audio_bytes, format="audio/mp3")
        st.download_button(
            f"Download {label}",
            data=audio_bytes,
            file_name=f"{label.lower().replace(' ', '_')}.mp3",
            mime="audio/mpeg",
            key=f"dl_{label}",
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

    st.title(f"📖 {APP_TITLE}")
    st.caption("Upload a PDF, ask questions with page citations, "
               "summarize, and listen.")

    if not OPENAI_API_KEY:
        st.error(
            "`OPENAI_API_KEY` is not set. Add it to your Streamlit secrets "
            "(or environment) before continuing.")

    section_privacy()
    section_upload()
    section_build_index()
    section_ask()
    section_summarize()
    section_audio()
    section_reset()


if __name__ == "__main__":
    main()
