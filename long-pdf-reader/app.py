"""
app.py — PDF Audio
"""
from __future__ import annotations

import base64
import os
from typing import Optional

import streamlit as st
import pdf_utils as pu

APP_TITLE    = "PDF Audio"
APP_SUBTITLE = "Turn any document into audio"
APP_ICON     = "🎧"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Layout ── */
  .block-container {
    padding-top: 0;
    padding-bottom: 6rem;
    max-width: 660px;
  }

  /* ── Hero header ── */
  .app-hero {
    text-align: center;
    padding: 3rem 1rem 1.8rem;
  }
  .app-hero .hero-icon {
    font-size: 3.8rem;
    line-height: 1;
    margin-bottom: 0.5rem;
    display: block;
  }
  .app-hero .hero-title {
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -1px;
    margin: 0 0 0.3rem;
    background: linear-gradient(135deg, #4f46e5, #818cf8);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .app-hero .hero-sub {
    font-size: 1rem;
    opacity: 0.45;
    margin: 0;
    font-weight: 400;
  }

  /* ── Section labels ── */
  .section-label {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    opacity: 0.38;
    margin: 0 0 0.6rem;
  }

  /* ── Upload zone ── */
  [data-testid="stFileUploadDropzone"] {
    border-radius: 20px !important;
    border: 2px dashed rgba(99,102,241,0.35) !important;
    padding: 2rem 1.5rem !important;
    background: rgba(99,102,241,0.04) !important;
    transition: border-color 0.2s, background 0.2s;
  }
  [data-testid="stFileUploadDropzone"]:hover {
    border-color: rgba(99,102,241,0.65) !important;
    background: rgba(99,102,241,0.08) !important;
  }

  /* ── Doc info pill ── */
  .doc-pill {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    background: rgba(99,102,241,0.08);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 14px;
    padding: 0.8rem 1.1rem;
    margin-bottom: 1.4rem;
    font-size: 0.92rem;
  }
  .doc-pill .doc-icon { font-size: 1.3rem; flex-shrink: 0; }
  .doc-pill .doc-name { font-weight: 600; flex: 1; }
  .doc-pill .doc-meta { opacity: 0.45; font-size: 0.82rem; white-space: nowrap; }

  /* ── Controls panel ── */
  .controls-panel {
    background: rgba(128,128,128,0.05);
    border: 1px solid rgba(128,128,128,0.11);
    border-radius: 20px;
    padding: 1.4rem 1.4rem 1rem;
    margin-bottom: 1rem;
  }

  /* ── Primary button ── */
  .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #4338ca 0%, #6366f1 100%) !important;
    border: none !important;
    color: #fff !important;
    border-radius: 14px !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    padding: 0.75rem 1rem !important;
    min-height: 48px !important;
    box-shadow: 0 4px 18px rgba(99,102,241,0.35) !important;
    transition: opacity 0.15s, box-shadow 0.15s !important;
    width: 100% !important;
  }
  .stButton > button[kind="primary"]:hover {
    opacity: 0.91 !important;
    box-shadow: 0 6px 24px rgba(99,102,241,0.45) !important;
  }
  .stButton > button[kind="secondary"],
  .stDownloadButton > button {
    border-radius: 12px !important;
    font-weight: 500 !important;
    min-height: 44px !important;
    width: 100% !important;
    transition: opacity 0.15s !important;
  }

  /* ── Form elements ── */
  .stSelectbox div[data-baseweb="select"],
  .stNumberInput input {
    border-radius: 11px !important;
    font-size: 0.95rem !important;
  }

  /* ── Player card ── */
  .player-card {
    background: linear-gradient(140deg, #1e1b4b 0%, #312e81 45%, #3730a3 100%);
    border-radius: 24px;
    padding: 1.5rem 1.4rem 1.2rem;
    margin: 0.5rem 0 0.8rem;
    box-shadow: 0 10px 40px rgba(67,56,202,0.35);
  }
  .player-doc { color: #fff; font-size: 1.05rem; font-weight: 700; margin-bottom: 0.2rem; }
  .player-meta {
    color: rgba(255,255,255,0.5);
    font-size: 0.8rem;
    margin-bottom: 1rem;
    display: flex;
    gap: 0.6rem;
    align-items: center;
  }
  .player-dot { color: rgba(255,255,255,0.25); }

  /* ── Alerts ── */
  .stAlert { border-radius: 14px !important; }
  .stSuccess { border-radius: 14px !important; }

  /* ── Misc ── */
  footer { display: none; }
  #MainMenu { display: none; }
  header[data-testid="stHeader"] { background: transparent; }
</style>
""", unsafe_allow_html=True)


# ── Session state ─────────────────────────────────────────────────────────────

def init_state():
    for k, v in {
        "doc_name":    None,
        "doc_size_mb": 0.0,
        "extraction":  None,
        "full_audio":  None,
        "audio_start": 1,
        "audio_end":   1,
    }.items():
        st.session_state.setdefault(k, v)


def reset_state():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    init_state()


# ── Upload section ────────────────────────────────────────────────────────────

def section_upload():
    st.markdown('<div class="section-label">Upload</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader(
        "Drop a PDF here",
        type=["pdf"],
        accept_multiple_files=False,
        label_visibility="collapsed",
    )
    if uploaded is None:
        return

    size_mb = uploaded.size / (1024 * 1024)
    if size_mb > pu.MAX_UPLOAD_MB:
        st.error(f"File is {size_mb:.1f} MB — limit is {pu.MAX_UPLOAD_MB} MB.")
        return

    # Re-extract only if file changed
    if (st.session_state.get("doc_name") != uploaded.name
            or st.session_state.get("extraction") is None):
        reset_state()
        st.session_state["doc_name"]    = uploaded.name
        st.session_state["doc_size_mb"] = size_mb
        with st.status("Reading PDF…", expanded=False) as s:
            try:
                result = pu.extract_pdf(uploaded.getvalue())
            except Exception as e:
                s.update(label="Failed", state="error")
                st.error(str(e))
                return
            st.session_state["extraction"] = result
            st.session_state["audio_end"]  = result.page_count
            s.update(label="Ready", state="complete")

    extraction: pu.ExtractionResult = st.session_state["extraction"]
    if extraction.error:
        st.error(extraction.error)
        return

    # Doc info pill
    name_clean = uploaded.name.replace(".pdf", "")
    st.markdown(
        f'<div class="doc-pill">'
        f'<span class="doc-icon">📄</span>'
        f'<span class="doc-name">{name_clean}</span>'
        f'<span class="doc-meta">{extraction.page_count} pages · {size_mb:.1f} MB</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if extraction.likely_scanned:
        st.warning("This PDF appears to be image-only — minimal text extracted.")

    return extraction


# ── Audio section ─────────────────────────────────────────────────────────────

def section_audio(extraction: pu.ExtractionResult):
    n = extraction.page_count

    st.markdown('<div class="controls-panel">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">Settings</div>', unsafe_allow_html=True)

    # Page range
    c1, c2 = st.columns(2)
    with c1:
        a_start = st.number_input("From page", min_value=1, max_value=n,
                                  value=st.session_state.get("audio_start", 1),
                                  step=1, key="audio_start")
    with c2:
        a_end = st.number_input("To page", min_value=1, max_value=n,
                                value=st.session_state.get("audio_end", n),
                                step=1, key="audio_end")

    # Voice + speed
    c3, c4 = st.columns(2)
    with c3:
        voice_label = st.selectbox("Voice", list(pu.EDGE_TTS_VOICES.keys()), key="voice")
    with c4:
        rate_label = st.selectbox("Speed", list(pu.EDGE_TTS_RATES.keys()), key="rate")

    st.markdown('</div>', unsafe_allow_html=True)

    span     = int(a_end) - int(a_start) + 1
    disabled = span <= 0 or span > pu.MAX_AUDIO_PAGES

    if span > pu.MAX_AUDIO_PAGES:
        st.warning(f"Maximum is {pu.MAX_AUDIO_PAGES} pages per run.")
    elif span > 0:
        st.caption(f"{span} page{'s' if span > 1 else ''} · free Microsoft neural TTS · no API key needed")

    if st.button("Generate audio", type="primary", disabled=disabled, key="gen_btn"):
        raw = pu.get_pages_text(extraction.pages, int(a_start), int(a_end))
        if not raw.strip():
            st.warning("No text found in the selected pages.")
            return

        clips   = pu.split_for_tts(raw)
        n_clips = len(clips)
        st.session_state["full_audio"] = None

        import concurrent.futures, threading
        results   = [None] * n_clips
        completed = [0]
        lock      = threading.Lock()
        progress  = st.progress(0.0, text=f"Generating audio…")

        edge_voice = pu.EDGE_TTS_VOICES[voice_label]
        edge_rate  = pu.EDGE_TTS_RATES[rate_label]

        def _gen(idx, text):
            audio = pu.tts_clip_edge(text, voice=edge_voice, rate=edge_rate)
            with lock:
                results[idx] = audio
                completed[0] += 1
                progress.progress(
                    completed[0] / n_clips,
                    text=f"Generating clip {completed[0]} of {n_clips}…"
                )

        errors = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_gen, i, c): i for i, c in enumerate(clips)}
            for f in concurrent.futures.as_completed(futs):
                if f.exception():
                    errors.append(str(f.exception()))

        progress.empty()
        good = [b for b in results if b]
        if good:
            st.session_state["full_audio"] = b"".join(good)
        if errors:
            st.warning(f"{len(errors)} clip(s) had errors and were skipped.")

    # ── Player ────────────────────────────────────────────────────────────────
    audio = st.session_state.get("full_audio")
    if not audio:
        return

    doc_name   = st.session_state.get("doc_name", "audio")
    name_clean = doc_name.replace(".pdf", "")
    safe_name  = name_clean.lower().replace(" ", "_").replace("/", "_")
    size_mb    = len(audio) / (1024 * 1024)
    title_js   = name_clean.replace("'", "\\'")

    b64 = base64.b64encode(audio).decode()
    player_html = f"""
<style>
  #pdfaudio {{
    width: 100%;
    border-radius: 10px;
    outline: none;
    accent-color: #818cf8;
    filter: invert(0);
  }}
</style>
<audio id="pdfaudio" controls preload="auto">
  <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
</audio>
<script>
(function(){{
  const a = document.getElementById('pdfaudio');
  if (!('mediaSession' in navigator)) return;
  navigator.mediaSession.metadata = new MediaMetadata({{
    title:  '{title_js}',
    artist: 'PDF Audio',
    album:  'Pages {int(a_start)}–{int(a_end)}',
  }});
  const upd = () => {{
    if (a.duration) navigator.mediaSession.setPositionState({{
      duration: a.duration, playbackRate: a.playbackRate, position: a.currentTime
    }});
  }};
  a.addEventListener('play',       () => navigator.mediaSession.playbackState = 'playing');
  a.addEventListener('pause',      () => navigator.mediaSession.playbackState = 'paused');
  a.addEventListener('timeupdate', upd);
  navigator.mediaSession.setActionHandler('play',         () => a.play());
  navigator.mediaSession.setActionHandler('pause',        () => a.pause());
  navigator.mediaSession.setActionHandler('seekforward',  d  => {{
    a.currentTime = Math.min(a.currentTime + (d.seekOffset || 30), a.duration);
  }});
  navigator.mediaSession.setActionHandler('seekbackward', d  => {{
    a.currentTime = Math.max(a.currentTime - (d.seekOffset || 30), 0);
  }});
}})();
</script>
"""

    st.markdown(
        f'<div class="player-card">'
        f'<div class="player-doc">{name_clean}</div>'
        f'<div class="player-meta">'
        f'Pages {int(a_start)}–{int(a_end)}'
        f'<span class="player-dot">·</span>'
        f'{size_mb:.1f} MB'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.components.v1.html(player_html, height=60)
    st.download_button(
        "⬇  Download MP3",
        data=audio,
        file_name=f"{safe_name}.mp3",
        mime="audio/mpeg",
        key="dl_audio",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_state()

    st.markdown(
        '<div class="app-hero">'
        '<span class="hero-icon">🎧</span>'
        f'<h1 class="hero-title">{APP_TITLE}</h1>'
        f'<p class="hero-sub">{APP_SUBTITLE}</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    extraction = section_upload()
    if extraction:
        section_audio(extraction)
        st.divider()
        if st.button("Start over", type="secondary"):
            reset_state()
            st.rerun()


if __name__ == "__main__":
    main()
