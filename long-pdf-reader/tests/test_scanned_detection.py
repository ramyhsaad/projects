"""Tests for is_likely_scanned and extract_pdf error paths."""
import pytest

from pdf_utils import DocPage, extract_pdf, is_likely_scanned


def test_is_likely_scanned_empty_pages_false():
    assert is_likely_scanned([]) is False


def test_is_likely_scanned_text_pdf_false():
    pages = [DocPage(i, "Normal page with plenty of extractable text. " * 10)
             for i in range(1, 6)]
    assert is_likely_scanned(pages) is False


def test_is_likely_scanned_image_pdf_true_low_avg():
    pages = [DocPage(i, "") for i in range(1, 11)]
    assert is_likely_scanned(pages) is True


def test_is_likely_scanned_mostly_empty_true():
    pages = [DocPage(i, "") for i in range(1, 10)]
    pages.append(DocPage(10, "A" * 5000))  # one fat page bumps avg
    # Avg might be high but empty_ratio > 0.8 catches it
    assert is_likely_scanned(pages) is True


def test_extract_pdf_empty_bytes():
    r = extract_pdf(b"")
    assert r.error is not None
    assert r.pages == []
    assert r.page_count == 0


def test_extract_pdf_garbage_bytes():
    r = extract_pdf(b"this is definitely not a pdf file")
    assert r.error is not None
    assert r.pages == []


def test_extract_pdf_minimal_blank_pdf():
    """Build a tiny valid PDF and confirm extraction reports it as 'scanned'."""
    fitz = pytest.importorskip("fitz")  # PyMuPDF
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.new_page(width=200, height=200)
    pdf_bytes = doc.tobytes()
    doc.close()

    r = extract_pdf(pdf_bytes)
    assert r.error is None
    assert r.page_count == 2
    assert len(r.pages) == 2
    # Page numbers preserved (1-indexed, no gaps)
    assert [p.page_number for p in r.pages] == [1, 2]
    # Blank pages -> avg chars/page is 0 -> likely_scanned True
    assert r.likely_scanned is True


def test_extract_pdf_with_real_text():
    """A PDF with actual text should not be flagged as scanned."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    body = (
        "This is a perfectly readable page of a test document. "
        "It contains plenty of extractable text suitable for chunking, "
        "embedding, and downstream question answering. The content is "
        "intentionally verbose so that the scanned-PDF heuristic does not "
        "false-positive on this synthetic input. " * 4
    )
    for i in range(3):
        page = doc.new_page(width=600, height=800)
        # Wrap text so it actually fits on the page
        page.insert_textbox(
            fitz.Rect(40, 40, 560, 760),
            f"Page {i + 1}.\n\n{body}",
            fontsize=10,
        )
    pdf_bytes = doc.tobytes()
    doc.close()

    r = extract_pdf(pdf_bytes)
    assert r.error is None
    assert r.page_count == 3
    assert r.likely_scanned is False
    assert r.total_chars > 500
    assert all((p.text or "").strip() for p in r.pages)
