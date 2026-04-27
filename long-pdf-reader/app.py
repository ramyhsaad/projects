"""
app.py — Text to Audio
"""
from __future__ import annotations
import time
import streamlit as st
import pdf_utils as pu

APP_TITLE    = "Text to Audio"
APP_SUBTITLE = "Turn any document into audio"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

WAVEFORM_SVG = """
<svg width="72" height="52" viewBox="0 0 72 52" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0"  y="20" width="8" height="12" rx="4" fill="#10b981"/>
  <rect x="12" y="10" width="8" height="32" rx="4" fill="#10b981"/>
  <rect x="24" y="2"  width="8" height="48" rx="4" fill="#10b981"/>
  <rect x="36" y="10" width="8" height="32" rx="4" fill="#10b981"/>
  <rect x="48" y="16" width="8" height="20" rx="4" fill="#10b981"/>
  <rect x="60" y="22" width="8" height="8"  rx="4" fill="#10b981"/>
</svg>
"""

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
html,body,[class*="css"]{font-family:'Inter',sans-serif!important;color:#0f172a!important;}
.block-container{padding-top:0;padding-bottom:6rem;max-width:680px;}
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{background:#ffffff!important;}
[data-testid="stHeader"]{background:#ffffff!important;}
section[data-testid="stSidebar"]{background:#f8fafc!important;}
.app-hero{text-align:center;padding:3rem 1rem 2rem;}
.hero-icon{display:flex;justify-content:center;margin-bottom:1rem;animation:wave-pulse 2.4s ease-in-out infinite;}
@keyframes wave-pulse{0%,100%{filter:drop-shadow(0 0 8px rgba(16,185,129,.4));}50%{filter:drop-shadow(0 0 22px rgba(16,185,129,.85));}}
.hero-title{font-size:2.4rem;font-weight:800;letter-spacing:-1.2px;margin:0 0 .4rem;color:#0f172a;line-height:1;}
.hero-sub{font-size:.95rem;color:#64748b;margin:0;font-weight:400;}
.section-label{font-size:.65rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:#94a3b8;margin:0 0 .7rem;}
[data-testid="stFileUploadDropzone"]{border-radius:16px!important;border:2px solid rgba(16,185,129,.35)!important;padding:2rem 1.5rem!important;background:#f0fdf4!important;transition:border-color .2s,box-shadow .2s;}
[data-testid="stFileUploadDropzone"]:hover{border-color:rgba(16,185,129,.7)!important;box-shadow:0 0 0 4px rgba(16,185,129,.08)!important;}
[data-testid="stFileUploadDropzone"] p,[data-testid="stFileUploadDropzone"] span{color:#64748b!important;font-family:'Inter',sans-serif!important;}
.doc-pill{display:flex;align-items:center;gap:.75rem;background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:.9rem 1.2rem;margin-bottom:1.5rem;}
.doc-icon{font-size:1.4rem;flex-shrink:0;}
.doc-name{font-weight:600;color:#0f172a;flex:1;font-size:.95rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.doc-meta{color:#94a3b8;font-size:.8rem;white-space:nowrap;}
.controls-panel{background:#f8fafc;border:1px solid #e2e8f0;border-radius:20px;padding:1.5rem 1.5rem 1rem;margin-bottom:1.2rem;}
.stSelectbox div[data-baseweb="select"]{background:#ffffff!important;border-color:#e2e8f0!important;border-radius:10px!important;}
.stSelectbox div[data-baseweb="select"]:hover{border-color:#10b981!important;}
.stSelectbox [data-baseweb="select"]>div{color:#0f172a!important;font-family:'Inter',sans-serif!important;}
.stNumberInput input{background:#ffffff!important;border-color:#e2e8f0!important;border-radius:10px!important;color:#0f172a!important;font-family:'Inter',sans-serif!important;}
.stNumberInput input:focus{border-color:#10b981!important;box-shadow:0 0 0 3px rgba(16,185,129,.12)!important;}
label[data-testid="stWidgetLabel"] p{color:#64748b!important;font-size:.85rem!important;font-family:'Inter',sans-serif!important;}
.stButton>button[kind="primary"]{background:#10b981!important;border:none!important;color:#ffffff!important;border-radius:500px!important;font-size:.95rem!important;font-weight:700!important;letter-spacing:.06em!important;padding:.8rem 2rem!important;min-height:52px!important;width:100%!important;text-transform:uppercase!important;transition:transform .1s,background .15s!important;}
.stButton>button[kind="primary"]:hover{background:#059669!important;transform:scale(1.02)!important;}
.stButton>button[kind="primary"]:active{transform:scale(.98)!important;background:#047857!important;}
.stButton>button[kind="secondary"]{background:#ffffff!important;border:1px solid #e2e8f0!important;color:#0f172a!important;border-radius:500px!important;font-weight:600!important;min-height:44px!important;width:100%!important;transition:background .15s,border-color .15s!important;}
.stButton>button[kind="secondary"]:hover{background:#f8fafc!important;border-color:#0f172a!important;}
.stDownloadButton>button{background:transparent!important;border:1px solid #e2e8f0!important;color:#0f172a!important;border-radius:500px!important;font-weight:600!important;min-height:44px!important;width:100%!important;font-size:.9rem!important;transition:border-color .15s,background .15s!important;}
.stDownloadButton>button:hover{border-color:#0f172a!important;background:rgba(15,23,42,.04)!important;}
.gen-status{background:#f0fdf4;border:1.5px solid #10b981;border-radius:16px;padding:1.2rem 1.4rem;margin-bottom:.8rem;}
.gen-status-title{color:#0f172a;font-weight:700;font-size:1rem;margin-bottom:.3rem;}
.gen-status-sub{color:#374151;font-size:.85rem;line-height:1.6;}
.gen-eta{color:#059669;font-weight:600;}
.gen-warn{color:#9ca3af;font-size:.75rem;margin-top:.3rem;}
.player-card{background:#f0fdf4;border-radius:20px;padding:1.6rem 1.5rem 1.2rem;margin:.6rem 0 .9rem;border:1.5px solid #a7f3d0;position:relative;overflow:hidden;}
.player-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#10b981,#34d399,#059669);border-radius:20px 20px 0 0;}
.player-card::after{content:'';position:absolute;bottom:0;right:1.2rem;width:90px;height:44px;background:repeating-linear-gradient(to right,rgba(16,185,129,.2) 0px,rgba(16,185,129,.2) 3px,transparent 3px,transparent 7px);-webkit-mask-image:linear-gradient(to top,rgba(0,0,0,.5),transparent);mask-image:linear-gradient(to top,rgba(0,0,0,.5),transparent);}
.player-doc{color:#0f172a;font-size:1.05rem;font-weight:700;margin-bottom:.2rem;}
.player-meta{color:#64748b;font-size:.8rem;margin-bottom:1rem;display:flex;gap:.5rem;align-items:center;}
.player-dot{color:#cbd5e1;}
audio{width:100%;border-radius:8px;accent-color:#10b981;outline:none;}
.stProgress>div>div>div{background:#10b981!important;border-radius:4px!important;}
.stProgress>div>div{background:#e2e8f0!important;border-radius:4px!important;}
.stAlert,.stWarning,.stError{border-radius:14px!important;}
.stCaption{color:#94a3b8!important;font-size:.8rem!important;text-align:center;}
hr{border-color:#f1f5f9!important;}
footer{display:none;}
#MainMenu{display:none;}
header[data-testid="stHeader"]{background:transparent;}
::-webkit-scrollbar{width:6px;}
::-webkit-scrollbar-track{background:#f8fafc;}
::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:3px;}
::-webkit-scrollbar-thumb:hover{background:#94a3b8;}
</style>
""", unsafe_allow_html=True)


def init_state():
    for k, v in {"doc_name": None, "doc_size_mb": 0.0, "extraction": None,
                  "full_audio": None, "audio_start": 1, "audio_end": 1}.items():
        st.session_state.setdefault(k, v)

def reset_state():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    init_state()


def section_upload():
    st.markdown('<div class="section-label">📄 &nbsp;Document</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Drop a PDF here", type=["pdf"],
                                accept_multiple_files=False, label_visibility="collapsed")
    if uploaded is None:
        return

    size_mb = uploaded.size / (1024 * 1024)
    if size_mb > pu.MAX_UPLOAD_MB:
        st.error(f"File is {size_mb:.1f} MB — limit is {pu.MAX_UPLOAD_MB} MB.")
        return

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

    name_clean = uploaded.name.replace(".pdf", "")
    st.markdown(
        f'<div class="doc-pill">'
        f'<span class="doc-icon">📄</span>'
        f'<span class="doc-name">{name_clean}</span>'
        f'<span class="doc-meta">{extraction.page_count} pages &nbsp;·&nbsp; {size_mb:.1f} MB</span>'
        f'</div>', unsafe_allow_html=True)

    if extraction.likely_scanned:
        st.warning("This PDF appears to be image-only — minimal text extracted.")
    return extraction


def _fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


def section_audio(extraction: pu.ExtractionResult):
    n = extraction.page_count

    st.markdown('<div class="controls-panel">', unsafe_allow_html=True)
    st.markdown('<div class="section-label">🎚 &nbsp;Settings</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        a_start = st.number_input("📄 From page", min_value=1, max_value=n,
                                  value=st.session_state.get("audio_start", 1),
                                  step=1, key="audio_start")
    with c2:
        a_end = st.number_input("📄 To page", min_value=1, max_value=n,
                                value=st.session_state.get("audio_end", n),
                                step=1, key="audio_end")
    c3, c4 = st.columns(2)
    with c3:
        voice_label = st.selectbox("🗣 Voice", list(pu.EDGE_TTS_VOICES.keys()), key="voice")
    with c4:
        rate_label = st.selectbox("⚡ Speed", list(pu.EDGE_TTS_RATES.keys()), key="rate")

    st.markdown('</div>', unsafe_allow_html=True)

    span     = int(a_end) - int(a_start) + 1
    disabled = span <= 0 or span > pu.MAX_AUDIO_PAGES

    if span > pu.MAX_AUDIO_PAGES:
        st.warning(f"Maximum is {pu.MAX_AUDIO_PAGES} pages per run.")
    elif span > 0:
        est_words     = span * 250
        est_audio_min = est_words / 150
        est_gen_sec   = max(10, span * 1.2)
        if span <= 5:
            hint = f"{span} page{'s' if span > 1 else ''} · free Microsoft neural TTS"
        else:
            hint = (f"{span} pages · ~{est_audio_min:.0f} min of audio · "
                    f"est. {_fmt_time(est_gen_sec)} to generate · keep this tab open")
        st.caption(hint)

    if st.button("▶  Generate Audio", type="primary", disabled=disabled, key="gen_btn"):
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
        t_start   = time.time()

        status_slot = st.empty()
        progress    = st.progress(0.0)

        def _render(done: int):
            elapsed = time.time() - t_start
            pct = done / n_clips if n_clips else 0
            if done == 0 or elapsed < 1:
                eta_str = "calculating…"
            else:
                rate = done / elapsed
                remaining = (n_clips - done) / rate
                eta_str = f"~{_fmt_time(remaining)} remaining"
            status_slot.markdown(
                f'<div class="gen-status">'
                f'<div class="gen-status-title">🎵 Generating audio &nbsp;'
                f'<span style="color:#10b981">{int(pct*100)}%</span></div>'
                f'<div class="gen-status-sub">'
                f'Clip <strong>{done}</strong> of <strong>{n_clips}</strong>'
                f' &nbsp;·&nbsp; Elapsed: <strong>{_fmt_time(elapsed)}</strong>'
                f' &nbsp;·&nbsp; <span class="gen-eta">{eta_str}</span>'
                f'</div>'
                f'<div class="gen-warn">⚠ Keep this tab open — closing will stop generation</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        _render(0)

        edge_voice = pu.EDGE_TTS_VOICES[voice_label]
        edge_rate  = pu.EDGE_TTS_RATES[rate_label]

        # Workers only write results — NO Streamlit calls inside threads
        def _gen(idx, text):
            audio = pu.tts_clip_edge(text, voice=edge_voice, rate=edge_rate)
            with lock:
                results[idx] = audio
                completed[0] += 1

        errors = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(_gen, i, c): i for i, c in enumerate(clips)}
            # Update UI from the main thread as each future completes
            for f in concurrent.futures.as_completed(futs):
                if f.exception():
                    errors.append(str(f.exception()))
                _render(completed[0])
                progress.progress(completed[0] / n_clips)

        elapsed_total = time.time() - t_start
        progress.empty()

        good = [b for b in results if b]
        if good:
            st.session_state["full_audio"] = b"".join(good)
            audio_mb = len(st.session_state["full_audio"]) / (1024 * 1024)
            status_slot.markdown(
                f'<div class="gen-status">'
                f'<div class="gen-status-title">✅ Done!</div>'
                f'<div class="gen-status-sub">'
                f'{n_clips} clips · {audio_mb:.1f} MB · {_fmt_time(elapsed_total)}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        else:
            status_slot.empty()

        if errors:
            st.warning(f"{len(errors)} clip(s) had errors and were skipped.")

    audio = st.session_state.get("full_audio")
    if not audio:
        return

    doc_name   = st.session_state.get("doc_name", "audio")
    name_clean = doc_name.replace(".pdf", "")
    safe_name  = name_clean.lower().replace(" ", "_").replace("/", "_")
    size_mb    = len(audio) / (1024 * 1024)

    st.markdown(
        f'<div class="player-card">'
        f'<div class="player-doc">{name_clean}</div>'
        f'<div class="player-meta">Pages {int(a_start)}–{int(a_end)}'
        f'<span class="player-dot">·</span>{size_mb:.1f} MB</div>'
        f'</div>', unsafe_allow_html=True)

    # Use st.audio() — handles large files safely; no base64 embedding
    st.audio(audio, format="audio/mp3")

    st.download_button("⬇  Download MP3", data=audio,
                       file_name=f"{safe_name}.mp3", mime="audio/mpeg", key="dl_audio")


def main():
    init_state()

    st.markdown(
        f'<div class="app-hero">'
        f'<div class="hero-icon">{WAVEFORM_SVG}</div>'
        f'<h1 class="hero-title">{APP_TITLE}</h1>'
        f'<p class="hero-sub">{APP_SUBTITLE}</p>'
        f'</div>', unsafe_allow_html=True)

    extraction = section_upload()
    if extraction:
        section_audio(extraction)
        st.divider()
        if st.button("Start over", type="secondary"):
            reset_state()
            st.rerun()


if __name__ == "__main__":
    main()
