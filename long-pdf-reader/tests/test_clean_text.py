"""Tests for clean_text and naturalize_for_speech."""
from pdf_utils import clean_text, naturalize_for_speech


def test_clean_text_empty_inputs():
    assert clean_text("") == ""
    assert clean_text(None) == ""  # type: ignore[arg-type]


def test_clean_text_strips_nulls():
    assert "\x00" not in clean_text("hello\x00world")


def test_clean_text_collapses_horizontal_whitespace():
    out = clean_text("Hello    world\t\tthis  is  spaced")
    assert "   " not in out
    assert "\t" not in out


def test_clean_text_normalizes_newlines():
    out = clean_text("line1\r\nline2\rline3")
    assert "\r" not in out
    assert out.count("\n") == 2


def test_clean_text_collapses_blank_runs():
    out = clean_text("para1\n\n\n\n\npara2")
    assert "\n\n\n" not in out
    assert "para1" in out and "para2" in out


def test_clean_text_repairs_hyphenated_line_breaks():
    out = clean_text("This is some informa-\ntion split across lines.")
    assert "information" in out
    assert "informa-" not in out


def test_clean_text_strips_leading_line_whitespace():
    out = clean_text("hello\n   world")
    assert "\n   " not in out
    assert "world" in out


def test_naturalize_joins_mid_paragraph_breaks():
    raw = ("This sentence is broken\nacross two lines.\n\n"
           "But this paragraph stays separate.")
    out = naturalize_for_speech(raw)
    assert "broken across" in out  # joined
    assert "\n\n" in out             # paragraph break preserved


def test_naturalize_preserves_breaks_after_sentence_punctuation():
    raw = "End of sentence.\nNew sentence starts here."
    out = naturalize_for_speech(raw)
    # Either a space or newline is fine after the period; key is it doesn't
    # mash the period and "New" together as one word.
    assert "sentence. " in out or "sentence.\n" in out
