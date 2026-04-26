# Long PDF Reader

A small private Streamlit app for reading long PDFs from your phone.

It can:

- Upload a long PDF
- Extract the text page by page
- Build a searchable index
- Answer questions with **page citations**
- Summarize a chosen page range
- Generate **natural audio clips** from a chosen page range (Audible/Alexa style)
- Run well in iPhone Safari, including from your Home Screen

This app is designed for one user at a time and is protected by a password.

---

## Quick start (local)

```bash
# 1. Get the code
git clone <your-repo-url> long-pdf-reader
cd long-pdf-reader

# 2. Install
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Set secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Open .streamlit/secrets.toml and fill in OPENAI_API_KEY and APP_PASSWORD

# 4. Run
streamlit run app.py
```

Then open the URL Streamlit prints (usually http://localhost:8501).

---

## Deploy on Streamlit Community Cloud

1. Push this folder to a **GitHub** repository.
   Make sure `.streamlit/secrets.toml` is **not** committed (it is in `.gitignore`).
2. Go to <https://share.streamlit.io>, sign in, click **New app**.
3. Pick your repo and branch. Set **Main file path** to `app.py`.
4. Click **Advanced settings** → **Secrets**, and paste:

   ```toml
   OPENAI_API_KEY = "sk-..."
   APP_PASSWORD = "pick-a-strong-password"
   ```

5. Click **Deploy**. After a minute you will get a public URL like
   `https://your-app.streamlit.app`.

The first time you open the URL you will see the password prompt.

---

## Required secrets

| Name | What it is |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key. Used for embeddings, chat, and TTS. |
| `APP_PASSWORD` | A password you pick. Anyone opening the URL needs it. |

If `APP_PASSWORD` is missing, the app shows a warning and runs **without** a password gate. Set it before sharing the link.

The app **never** prints either secret in the UI or logs.

---

## Use it on your iPhone

See [PHONE_SETUP_GUIDE.md](PHONE_SETUP_GUIDE.md) for step-by-step instructions including **Add to Home Screen**.

In short:

1. Open your Streamlit URL in **Safari**.
2. Tap **Share** → **Add to Home Screen**.
3. Open it from your Home Screen — it now behaves like an app.

---

## How it works

```
1. Upload PDF
   ↓
2. Read pages    (page-by-page text extraction; scanned-PDF detection)
   ↓
3. Build index   (chunk + embed with text-embedding-3-small)
   ↓
4. Use it
   ├─ Ask a question     → top-k retrieval + gpt-4o-mini answers with (p. N) citations
   ├─ Summarize range    → map-reduce summary in your chosen style
   └─ Listen             → gpt-4o-mini-tts, split into 1.5–2 min clips
```

All AI calls use the official OpenAI Python SDK and are wrapped in retries for transient errors (rate limits, timeouts).

---

## Hard limits (configurable in `pdf_utils.py`)

| Limit | Default |
|---|---|
| Max upload size | 50 MB |
| Max summary span | 60 pages / 40 chunks |
| Max audio span | 12 pages |
| Max audio clips per run | 6 |
| Max retrieved excerpts for Q&A | 12 |

These prevent surprise costs. Adjust the constants at the top of `pdf_utils.py` if you need more headroom.

---

## Privacy

- Your PDF is held only in the current Streamlit session and dropped on reload. The app never writes it to disk.
- Excerpts of the PDF **are sent to OpenAI** when you build the index, ask a question, summarize, or generate audio. This is unavoidable for those features.
- Your password is checked locally and never sent to OpenAI.

---

## Tests

```bash
pip install pytest
python -m py_compile app.py pdf_utils.py
pytest -q
```

The test suite uses a fake OpenAI client, so **no real API calls are made**.

---

## Known limitations

- **No OCR.** Scanned/image-only PDFs are detected and flagged with instructions, but the app will not turn them into text. Run `ocrmypdf input.pdf output.pdf` first.
- **One PDF at a time.** Designed for focused reading on a phone. Upload a new PDF to switch.
- **No persistent storage.** Reload = start over. This is intentional for privacy and simplicity.
- **OpenAI dependency.** All AI features require a valid `OPENAI_API_KEY` with billing enabled.
- **Single-user assumption.** The password gate is a basic shared-secret. It is not designed for multi-tenant use.

---

## What would be needed before "production-grade"

- Proper auth (per-user accounts, password rotation, lockout)
- HTTPS-only enforcement and a custom domain
- Server-side rate limiting per session
- Optional OCR fallback (`ocrmypdf` or a vision model) for scanned PDFs
- Persistent embedding cache (so repeat uploads of the same PDF don't re-embed)
- Observability: structured logging and error reporting
- A small budget cap (max $/session) enforced server-side
