# iPhone Setup Guide

The non-technical version. You need: an iPhone with Safari, a Streamlit Community Cloud account, an OpenAI API key, and a GitHub account.

## 1) One-time deploy (do this once on a computer)

1. Put this folder in a **GitHub** repo (private is fine).
2. Go to <https://share.streamlit.io>, click **New app**, pick your repo.
3. Set **Main file path** to `app.py`.
4. Open **Advanced settings** → **Secrets** and paste:

   ```toml
   OPENAI_API_KEY = "sk-..."
   APP_PASSWORD = "pick-a-strong-password"
   ```

5. Click **Deploy**.
6. Wait about a minute. You'll get a URL like `https://long-pdf-reader.streamlit.app`.

## 2) Add it to your iPhone Home Screen

1. Open the URL on your iPhone in **Safari** (not Chrome — Safari is the only browser that supports Add to Home Screen properly).
2. Tap the **Share** icon (the square with the arrow pointing up).
3. Scroll and tap **Add to Home Screen**.
4. Name it something short like *PDF Reader*.
5. Tap **Add**.

The app icon now lives on your Home Screen and opens like a normal app.

## 3) Daily use

1. Tap the **PDF Reader** icon on your Home Screen.
2. Type your `APP_PASSWORD` (Safari can save it for you).
3. Tap **Upload PDF** and pick a file (under 50 MB).
4. The app reads the PDF automatically.
5. Tap **Build index**. Wait a few seconds.
6. From here you can:
   - **Ask** a question — get an answer with page citations.
   - **Summarize** a page range — pick start and end page.
   - **Listen** — pick a small range (3 to 8 pages works well), choose voice and style, tap **Generate audio**.

## Tips for the best experience

- For audio, **smaller is better**: 3–8 pages at a time sounds more natural and is faster than one giant clip.
- The "Warm audiobook" style sounds the most natural. The "Alexa-like clear narrator" style is best when you're walking around.
- If you upload a scanned PDF (a photo of pages, not real text), the app will warn you and explain how to add OCR on your computer first.
- To switch to a different PDF, scroll to the bottom and tap **Start over with a new PDF**.

## What if the password prompt won't go away?

- Double-check the password matches exactly what you put in Streamlit secrets (no trailing spaces).
- If you changed the secret in Streamlit Cloud, it can take up to a minute to redeploy.
- If you fully forgot it, change `APP_PASSWORD` in the Streamlit secrets — the next reload will use the new value.

## What if "OpenAI rejected the API key" appears?

- Your `OPENAI_API_KEY` secret is wrong or revoked. Generate a new one at <https://platform.openai.com/api-keys> and update it in Streamlit secrets.
