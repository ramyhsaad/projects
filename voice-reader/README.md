# Voice Reader

Reads a PDF aloud in a cloned voice with [Chatterbox](https://github.com/resemble-ai/chatterbox)
and saves it as an MP3. It runs on your Mac. You give it a 10–20 second WAV of the voice you want.

## Run it

```bash
bash read.sh "The Soul, Whence and Whither - Inayat Khan.pdf" pv_ref_E.wav "The Soul.mp3" --pages 2-66 --expression 0.6 --pace 0.4 --speed 0.85
```

The first time, `read.sh` uses a Python that already has Chatterbox (`.venv`, `venv` or `env`
in this folder). If there isn't one, it creates `.venv` and installs Chatterbox, which takes
a few GB.

You'll see one line per passage:

```
Passage 37 of 1210  (6.2 s, 1.4x real time)  elapsed 4m 10s, about 2h 05m left
```

## Listening feel

- **Speed.** `--speed 0.9` (the default) slows the finished MP3 without lowering the voice.
  Try `0.85` or `0.8` for a slower, more deliberate delivery. Changing it remakes nothing.
- **Pauses.** Sentences, paragraphs and lectures get pauses of 0.4, 1 and 4 seconds.
  `--pauses 1.5` makes every pause half again as long.
- **Lecture breaks.** A heading set in larger type than the body text starts a new lecture:
  a long pause, the heading read on its own, and a chapter marker in the MP3. Check what it
  found with `--dry-run`. If it misses one, name the pages: `--break-pages 5,19,33`.
- **Pronunciation.** `pronunciations.txt` respells words before they're spoken
  (`Zat = Zaht`). It has more Sufi terms to check with your guide and switch on. After an
  edit, run the same command again: only the passages with those words are remade.

## Stop and continue

- Press **Ctrl‑C** once and it stops after the current passage. Press it twice to stop at once.
- Run the same command again and it continues where it stopped. Finished passages are saved
  in `<name>.parts/` next to the MP3.
- Changing `--expression`, `--pace`, the voice file or `--model` makes the passages again. Use
  `--fresh` to start over anyway.

## If it's slow

Time one passage on each device first:

```bash
bash read.sh "book.pdf" pv_ref_E.wav --pages 2-2 --bench
```

Then pass the fastest with `--device cpu` or `--device mps`. Over 20x real time usually means
the Mac is out of memory and swapping: quit Chrome, Zoom and other big apps, and keep
10 GB or more of disk free.

For more speed, `--model turbo` uses Chatterbox Turbo. It's several times faster but ignores
`--expression` and `--pace`.

## Options

| Option | What it does |
| --- | --- |
| `--pages 2-66` | Pages to read; also `1,3,5-7` or `10-` |
| `--expression 0.6` | Emotion, 0.25 flat to 1.0 dramatic (default 0.5) |
| `--pace 0.5` | Lower is slower and more deliberate, 0.2–0.8 (default 0.5) |
| `--speed 0.9` | Final speed, pitch kept; lower is slower (0.5–2.0) |
| `--pauses 1.0` | Multiply all pauses |
| `--break-pages 5,19` | Pages where a new lecture starts, besides detected headings |
| `--pronounce FILE` | Respelling list (default `pronunciations.txt`) |
| `--device auto` | `cpu`, `mps` (Apple GPU) or `cuda` |
| `--model standard` | `turbo` for the faster model |
| `--max-chars 250` | Longest passage. Shorter passages finish sooner and wander less. |
| `--dry-run` | Show the passages it will read, then stop |
| `--bench` | Time one passage on each device, then stop |
| `--fresh` | Ignore saved passages |

It skips repeated headers, footers, page numbers, `[12]`-style citations and links. If a
passage runs far longer than its text should take, it tries that passage again. The MP3
needs `ffmpeg` (`brew install ffmpeg`); without it you get a WAV.

## Test without the model

```bash
python3 voice_reader.py book.pdf any.wav out.mp3 --pages 1-3 --engine fake
python3 -m pytest tests
```
