"""Audio player for Text to Audio.

The MP3 itself is served by st.audio (a normal URL, so long books stream and
keep playing with the screen locked). This component draws the player and
drives that <audio> element in the parent page. If it can't reach it, the
plain st.audio player stays visible instead.
"""
from __future__ import annotations

import json
from typing import List, Tuple

AUDIO_KEY = "tta_audio"  # st.container key that wraps st.audio

_HTML = r"""<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Inter,-apple-system,BlinkMacSystemFont,system-ui,sans-serif;background:transparent;padding:2px;color:#f8fafc;-webkit-font-smoothing:antialiased}
.card{background:#0f172a;border-radius:22px;padding:20px 20px 16px;border:1px solid #1e293b}
.title{font-size:17px;font-weight:700;line-height:1.3;color:#f8fafc;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.meta{font-size:13px;color:#94a3b8;margin-top:4px}
.bars{display:flex;align-items:flex-end;gap:2px;height:46px;margin:18px 0 6px;cursor:pointer;touch-action:none}
.bars i{flex:1;background:#334155;border-radius:2px;min-height:3px}
.bars i.on{background:#10b981}
.bars i.now{background:#6ee7b7}
.times{display:flex;justify-content:space-between;font-size:12px;color:#94a3b8;font-variant-numeric:tabular-nums}
.where{text-align:center;color:#cbd5e1}
.row{display:flex;align-items:center;justify-content:center;gap:26px;margin:16px 0 14px}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer;-webkit-tap-highlight-color:transparent}
.skip{position:relative;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;color:#e2e8f0}
.skip svg{width:34px;height:34px}
.skip b{position:absolute;font-size:11px;font-weight:700;top:20px}
.skip:active{background:rgba(255,255,255,.08)}
.play{width:68px;height:68px;border-radius:50%;background:#10b981;color:#052e22;display:grid;place-items:center;box-shadow:0 6px 22px rgba(16,185,129,.35)}
.play:active{transform:scale(.96);background:#059669}
.play svg{width:28px;height:28px}
.tools{display:flex;gap:8px}
.chip{flex:1;min-height:44px;border-radius:12px;background:#1e293b;color:#e2e8f0;font-size:14px;font-weight:600;display:flex;align-items:center;justify-content:center;gap:6px;padding:0 10px;position:relative;overflow:hidden}
.chip small{font-weight:500;color:#94a3b8}
.chip select{position:absolute;inset:0;opacity:0;font-size:16px;width:100%}
.note{display:none;font-size:13px;color:#94a3b8;margin-top:10px;text-align:center}
.fallback .card{display:none}
:focus-visible{outline:2px solid #6ee7b7;outline-offset:2px}
</style></head>
<body>
<div class="card">
  <div class="title" id="title"></div>
  <div class="meta" id="meta"></div>
  <div class="bars" id="bars" role="slider" tabindex="0" aria-label="Position"></div>
  <div class="times"><span id="cur">0:00</span><span class="where" id="where"></span><span id="left">0:00</span></div>
  <div class="row">
    <button class="skip" id="back" aria-label="Back 15 seconds"><svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 13.5A13 13 0 1 1 7 21"/><path d="M8.5 6.5v7.5H16"/></svg><b>15</b></button>
    <button class="play" id="play" aria-label="Play"></button>
    <button class="skip" id="fwd" aria-label="Forward 30 seconds"><svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M30.5 13.5A13 13 0 1 0 33 21"/><path d="M31.5 6.5v7.5H24"/></svg><b>30</b></button>
  </div>
  <div class="tools">
    <button class="chip" id="speed" aria-label="Playback speed"><small>Speed</small><span id="speedv">1×</span></button>
    <label class="chip"><small>Section</small><span id="secv">1</span><select id="sections" aria-label="Jump to a section"></select></label>
  </div>
  <div class="note" id="note"></div>
</div>
<script>
const DATA = __DATA__;
const PLAY = '<svg viewBox="0 0 24 24"><path d="M8 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.2 4.5A.8.8 0 0 0 8 5.2z" fill="currentColor"/></svg>';
const PAUSE = '<svg viewBox="0 0 24 24"><rect x="6" y="5" width="4.2" height="14" rx="1.2" fill="currentColor"/><rect x="13.8" y="5" width="4.2" height="14" rx="1.2" fill="currentColor"/></svg>';
const SPEEDS = [1, 1.25, 1.5, 1.75, 2, 0.8];
const $ = (id) => document.getElementById(id);
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
const posKey = 'tta:pos:' + DATA.id;
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };

$('title').textContent = DATA.title;
$('meta').textContent = DATA.meta;
$('play').innerHTML = PLAY;
const secs = DATA.sections;
secs.forEach((s, i) => { const o = document.createElement('option'); o.value = i; o.textContent = s.label + ' (' + fmt(s.start) + ')'; $('sections').appendChild(o); });

// One bar per section; its height follows how long the section is.
const N = secs.length;
const lens = secs.map((s, i) => (i + 1 < N ? secs[i + 1].start : DATA.duration) - s.start);
const maxLen = Math.max(...lens, 1);
lens.forEach((l) => { const b = document.createElement('i'); b.style.height = (20 + 80 * Math.sqrt(l / maxLen)) + '%'; $('bars').appendChild(b); });

let a = null, tries = 0, lastSave = 0;
const host = window.parent && window.parent.document;
function sectionAt(t) { let i = 0; while (i + 1 < N && secs[i + 1].start <= t) i++; return i; }
function draw() {
  const t = a ? a.currentTime : 0, d = DATA.duration || (a && a.duration) || 0;
  const cur = sectionAt(t);
  [...$('bars').children].forEach((b, i) => { b.className = i < cur ? 'on' : i === cur ? 'now' : ''; });
  $('cur').textContent = fmt(t);
  $('left').textContent = '−' + fmt(d - t);
  $('where').textContent = secs[cur] ? secs[cur].label : '';
  $('secv').textContent = (cur + 1) + ' of ' + N;
  $('sections').value = cur;
  $('bars').setAttribute('aria-valuetext', fmt(t) + ' of ' + fmt(d));
}
function playstate() {
  const on = a && !a.paused;
  $('play').innerHTML = on ? PAUSE : PLAY;
  $('play').setAttribute('aria-label', on ? 'Pause' : 'Play');
}
function seek(t) { if (!a) return; a.currentTime = Math.max(0, Math.min((DATA.duration || a.duration || 0) - 0.25, t)); draw(); }
function setSpeed(r) { if (a) { a.playbackRate = r; a.preservesPitch = true; } $('speedv').textContent = r + '×'; store.set('tta:speed', r); }

function attach() {
  const box = host && host.querySelector('.st-key-' + DATA.audioKey);
  a = box && box.querySelector('audio');
  if (!a) {
    if (tries++ < 50) return setTimeout(attach, 100);
    document.body.classList.add('fallback');
    return;
  }
  box.style.display = 'none';
  if (!a.dataset.ttaWired) {
    a.dataset.ttaWired = '1';
    const saved = store.get(posKey, 0);
    const restore = () => { if (saved > 5 && saved < DATA.duration - 5 && a.currentTime < 1) a.currentTime = saved; };
    if (a.readyState >= 1) restore(); else a.addEventListener('loadedmetadata', restore, { once: true });
  }
  a.addEventListener('timeupdate', () => {
    draw();
    if (Date.now() - lastSave > 4000) { lastSave = Date.now(); store.set(posKey, a.currentTime); }
    try { window.parent.navigator.mediaSession.setPositionState({ duration: DATA.duration, position: Math.min(a.currentTime, DATA.duration), playbackRate: a.playbackRate }); } catch (e) {}
  });
  a.addEventListener('play', playstate);
  a.addEventListener('pause', () => { playstate(); store.set(posKey, a.currentTime); });
  a.addEventListener('ended', () => { playstate(); store.set(posKey, 0); });
  setSpeed(store.get('tta:speed', 1));
  mediaSession();
  draw();
  playstate();
}

function mediaSession() {
  const nav = window.parent.navigator;
  if (!nav || !('mediaSession' in nav)) return;
  try {
    nav.mediaSession.metadata = new window.parent.MediaMetadata({
      title: DATA.title, artist: 'Text to Audio', album: DATA.meta,
      artwork: [{ src: new URL('app/static/icon-512.png', window.parent.location.href).href, sizes: '512x512', type: 'image/png' }],
    });
  } catch (e) {}
  const h = (k, f) => { try { nav.mediaSession.setActionHandler(k, f); } catch (e) {} };
  h('play', () => a.play());
  h('pause', () => a.pause());
  h('seekbackward', () => seek(a.currentTime - 15));
  h('seekforward', () => seek(a.currentTime + 30));
  h('seekto', (d) => d && seek(d.seekTime));
  h('previoustrack', () => { const c = sectionAt(a.currentTime); seek(secs[a.currentTime - secs[c].start > 4 ? c : Math.max(0, c - 1)].start); });
  h('nexttrack', () => { const c = sectionAt(a.currentTime); if (c + 1 < N) seek(secs[c + 1].start); });
}

$('play').addEventListener('click', () => { if (!a) return; if (a.paused) { const p = a.play(); if (p && p.catch) p.catch(() => { $('note').style.display = 'block'; $('note').textContent = 'Tap play again to start.'; }); } else a.pause(); });
$('back').addEventListener('click', () => seek(a.currentTime - 15));
$('fwd').addEventListener('click', () => seek(a.currentTime + 30));
$('speed').addEventListener('click', () => { const cur = a ? a.playbackRate : 1; const i = SPEEDS.indexOf(cur); setSpeed(SPEEDS[(i + 1) % SPEEDS.length]); });
$('sections').addEventListener('change', (e) => seek(secs[Number(e.target.value)].start + 0.05));
let drag = false;
const fromX = (e) => { const r = $('bars').getBoundingClientRect(); const f = Math.max(0, Math.min(0.999, (e.clientX - r.left) / r.width)); const i = Math.floor(f * N); const within = f * N - i; return secs[i].start + within * lens[i]; };
$('bars').addEventListener('pointerdown', (e) => { drag = true; $('bars').setPointerCapture(e.pointerId); seek(fromX(e)); });
$('bars').addEventListener('pointermove', (e) => { if (drag) seek(fromX(e)); });
$('bars').addEventListener('pointerup', () => { drag = false; });
$('bars').addEventListener('keydown', (e) => { if (e.key === 'ArrowLeft') seek(a.currentTime - 15); if (e.key === 'ArrowRight') seek(a.currentTime + 30); });
attach();
</script></body></html>"""


def player_html(*, doc_id: str, title: str, meta: str,
                sections: List[Tuple[str, float]], duration: float) -> str:
    data = {
        "id": doc_id,
        "title": title,
        "meta": meta,
        "duration": duration,
        "audioKey": AUDIO_KEY,
        "sections": [{"label": label, "start": round(start, 2)} for label, start in sections] or [{"label": "Start", "start": 0}],
    }
    # Escape "</" so a title can't close the script tag.
    return _HTML.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
