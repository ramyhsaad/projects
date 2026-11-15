# voice-reader

Reads a PDF aloud in a cloned voice with Chatterbox, and saves one MP3.

```
bash read.sh "BOOK.pdf" VOICE.wav "OUT.mp3" --pages 2-66 --expression 0.6 --pace 0.5
```

`read.sh` uses the Python environment in `~/my-voice`. Set `VOICE_ENV` to use another one.

## Before a long run

- `--list-chapters` lists the lectures/chapters it found, with page numbers.
- `--dry-run` prints every passage (numbered) and the pauses, without making audio.

## Fixing what you hear

| Problem | What to do |
|---|---|
| Too fast | `--speed 0.8` (default 0.85). Slows the audio without changing pitch. A lower `--pace` (e.g. 0.3) also gives slower, more deliberate delivery. |
| Breaks between lectures | `--chapter-pause 5` (default 4 s). Also `--para-pause` (1.2 s) and `--passage-pause` (0.5 s). |
| A word said wrong | Add `word = how to say it` to `pronunciations.txt` and rerun. |
| A spotty / garbled bit | Find its number in the progress lines or `--dry-run`, then rerun with `--redo 145` (or `--redo 145,210-212`). |
| One lecture only | `--chapter 3` (numbers from `--list-chapters`). |
| Headings not found | `--heading-regex '^LECTURE'` |
| AI note at the start | `--intro "AI narration in the voice of Pir Vilayat Inayat Khan, made from archive recordings."` |

## Stopping and restarting

Every passage is saved in `OUT.parts/` as it is made. Ctrl-C at any time.
Run the same command again and it picks up where it stopped. Changing a
pronunciation or `--redo` remakes only those passages. Changing the voice
file, `--expression`, `--pace` or `--temperature` remakes everything.
Pauses and `--speed` cost nothing to change: they apply when the passages are joined.

Passages that come out far too long (the voice rambling) or far too short
(words dropped) are retried up to three times automatically, and every
passage is evened out to the same loudness.

If the first passages print "Slow", stop and rerun with `--device cpu`
(or `--device mps`). Finished passages are kept.
