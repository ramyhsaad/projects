"""Tests for the narration pipeline: header removal, parts, audio length."""
import shutil
import subprocess

import pytest

import pdf_utils as pu
from pdf_utils import DocPage


def test_strip_running_lines_removes_headers_and_page_numbers():
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    pages = [[
        "THE LAMP AND THE FIELD",
        f"The {w} passage opens this page with words of its own.",
        f"And a {w} line closes it differently.",
        str(i + 1),
    ] for i, w in enumerate(words)]
    out, removed = pu.strip_running_lines(pages)
    assert removed == 16
    for blocks in out:
        assert len(blocks) == 2
        assert "THE LAMP AND THE FIELD" not in blocks


def test_strip_running_lines_keeps_short_documents():
    pages = [["Title", "Body one."], ["Title", "Body two."]]
    out, removed = pu.strip_running_lines(pages)
    assert removed == 0
    assert out == pages


def test_naturalize_drops_citations_and_links():
    t = pu.naturalize_for_speech("See the result [12]. More at https://x.com/a and [3–5] here.")
    assert t == "See the result. More at link and here."


def _words(s):
    return s.split()


def test_build_parts_keeps_every_word_within_limit():
    para = "This is a sentence about reading long documents aloud. "
    pages = [DocPage(i + 1, para * 12 + "\n\n" + para * 5) for i in range(30)]
    parts = pu.build_parts(pages, max_chars=1500)
    assert len(parts) > 5
    assert all(len(p.text) <= 1500 for p in parts)
    expected = sum(len(_words(pu.naturalize_for_speech(p.text))) for p in pages)
    assert sum(len(_words(p.text)) for p in parts) == expected
    assert parts[0].page_start == 1 and parts[-1].page_end == 30
    starts = [p.page_start for p in parts]
    assert starts == sorted(starts)


def test_build_parts_joins_sentence_across_page_turn():
    parts = pu.build_parts([
        DocPage(1, "The argument begins on one page and"),
        DocPage(2, "ends on the next page. Then more."),
    ])
    assert len(parts) == 1
    assert parts[0].text == "The argument begins on one page and ends on the next page. Then more."
    assert (parts[0].page_start, parts[0].page_end) == (1, 2)


def test_build_parts_splits_giant_sentence_on_words():
    text = " ".join(f"word{i}" for i in range(900))
    parts = pu.build_parts([DocPage(3, text)], max_chars=1000)
    assert all(len(p.text) <= 1000 for p in parts)
    assert " ".join(p.text for p in parts).split() == text.split()


def test_build_parts_empty():
    assert pu.build_parts([DocPage(1, ""), DocPage(2, "   ")]) == []


def test_estimate_seconds_follows_rate():
    assert pu.estimate_seconds(1500) == pytest.approx(100)
    assert pu.estimate_seconds(1500, "-30%") > pu.estimate_seconds(1500)
    assert pu.estimate_seconds(1500, "+15%") < pu.estimate_seconds(1500)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_mp3_duration_matches_encoder(tmp_path):
    out = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-ar", "24000", "-ac", "1", "-b:a", "48k", str(out)], check=True)
    assert pu.mp3_duration(out.read_bytes()) == pytest.approx(3.0, abs=0.15)
    assert pu.mp3_duration(b"\x00\x01\xff\xff\x00") == 0


def test_tts_retry_recovers(monkeypatch):
    calls = {"n": 0}

    def flaky(text, voice, rate):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("dropped")
        return b"mp3"

    monkeypatch.setattr(pu, "tts_clip_edge", flaky)
    assert pu.tts_clip_edge_retry("hi", "v", "+0%", sleep=lambda s: None) == b"mp3"
    calls["n"] = -10
    with pytest.raises(RuntimeError):
        pu.tts_clip_edge_retry("hi", "v", "+0%", attempts=2, sleep=lambda s: None)
