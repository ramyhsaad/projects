import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import voice_reader as vr  # noqa: E402


def test_parse_pages():
    assert vr.parse_pages("2-4", 10) == [2, 3, 4]
    assert vr.parse_pages("1,3,5-6", 10) == [1, 3, 5, 6]
    assert vr.parse_pages("8-", 10) == [8, 9, 10]
    assert vr.parse_pages("5-80", 10) == [5, 6, 7, 8, 9, 10]
    assert vr.parse_pages(None, 3) == [1, 2, 3]
    with pytest.raises(ValueError):
        vr.parse_pages("abc", 10)


def test_passages_are_short_and_keep_every_word():
    para = ("This is a fairly ordinary sentence about the soul. " * 6
            + "Here is one enormous sentence, " + "which goes on and on, " * 30 + "and finally ends.")
    passages = vr.make_passages([para, "A second paragraph."], max_chars=250)
    assert all(len(p.text) <= 250 for p in passages)
    assert " ".join(p.text for p in passages).split() == (para + " A second paragraph.").split()
    ends = [p.paragraph_end for p in passages]
    assert ends[-1] and ends[-2] and not any(ends[:-2])


def test_running_headers_and_page_numbers_dropped():
    bodies = ["The soul comes from the light.", "It travels through the planes.",
              "Each plane leaves an impression.", "The heart longs for its home.",
              "Patience shows the way back.", "And so the journey ends."]
    pages = [["BOOK TITLE", b, str(i)] for i, b in enumerate(bodies, 1)]
    assert vr.strip_running_lines(pages) == [[b] for b in bodies]


def test_pronunciations_whole_words_keep_capital(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("# comment\nZat = Zaht   # ah sound\npir = Peer\n")
    pairs = vr.load_pronunciations(f)
    assert pairs == [("Zat", "Zaht"), ("pir", "Peer")]
    out = vr.apply_pronunciations("Zat and zat, not Zatara. Pir Vilayat's pir.", pairs)
    assert out == "Zaht and zaht, not Zatara. Peer Vilayat's peer."


def test_lecture_breaks_from_headings_and_pages():
    paras = [vr.Para("Intro text.", 1), vr.Para("The Coming of the Soul", 2, True),
             vr.Para("First lecture.", 2), vr.Para("Second lecture starts here.", 5)]
    ps = vr.make_passages(paras, break_pages=[5])
    assert [p.break_before for p in ps] == [False, True, False, True]
    assert vr.gap_after(ps[0], ps[1]) == vr.PAUSE_LECTURE_S
    assert vr.gap_after(ps[1], ps[2]) == vr.PAUSE_AFTER_HEADING_S
    assert vr.gap_after(ps[2], ps[3], 2.0) == vr.PAUSE_LECTURE_S * 2
