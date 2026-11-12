# Text to Audio

A Streamlit app that turns a PDF into an MP3 you can listen to on your phone.
It reads the PDF's text, removes repeated headers, footers and page numbers,
and narrates the pages you choose with Microsoft Edge neural voices
(through the free `edge-tts` library). No API key is needed.

## Features

- Upload a PDF of up to 200 MB and see its pages as bars sized by how much text each holds.
- Pick a page range, one of six voices (with a sample) and a reading pace.
- Make the MP3 in parallel parts, with progress and time left.
- Listen in the built-in player: skip back 15 seconds or forward 30 seconds, change speed,
  jump to sections by page, and keep listening with the screen locked.
- Download the MP3. On iPhone it's saved to Downloads in the Files app.
- Add the app to your iPhone Home Screen: in Safari, tap **Share** > **Add to Home Screen**.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

To try the app without network access, set `TTA_FAKE_TTS=1`. The app then
makes tones instead of speech.

## Deploy on Streamlit Community Cloud

Push the folder to GitHub, then create an app at <https://share.streamlit.io>
with `long-pdf-reader/app.py` as the main file. The app needs no secrets.

## Tests

```bash
python -m pytest -q tests/test_narration.py tests/test_clean_text.py tests/test_chunking.py tests/test_scanned_detection.py
```

## Files

- `app.py`: the Streamlit interface.
- `player.py`: the audio player shown after an MP3 is made.
- `pdf_utils.py`: PDF reading, text cleanup, splitting into parts and the Edge voices.
- `static/`: the Home Screen icon and web app manifest.
