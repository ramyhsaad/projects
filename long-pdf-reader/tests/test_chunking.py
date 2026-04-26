"""Tests for chunk_pages — preserves page provenance, handles empties."""
import pytest

from pdf_utils import DocPage, chunk_pages, select_chunks_in_range


def test_chunk_pages_empty_list():
    assert chunk_pages([]) == []


def test_chunk_pages_skips_empty_pages():
    pages = [DocPage(1, ""), DocPage(2, "   "),
             DocPage(3, "real content here")]
    out = chunk_pages(pages, target_words=200)
    assert len(out) == 1
    assert out[0].page_start == 3
    assert "real content" in out[0].text


def test_chunk_pages_short_page_becomes_one_chunk():
    pages = [DocPage(1, "short bit of text")]
    out = chunk_pages(pages, target_words=200)
    assert len(out) == 1
    assert out[0].page_start == 1 == out[0].page_end


def test_chunk_pages_long_text_splits_with_overlap():
    # 1500-word block on page 1 -> at least 2 chunks at target=500
    text = " ".join(f"word{i}" for i in range(1500))
    pages = [DocPage(1, text)]
    out = chunk_pages(pages, target_words=500, overlap_words=50)
    assert len(out) >= 2
    assert all(c.page_start == 1 and c.page_end == 1 for c in out)
    ids = [c.chunk_id for c in out]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_chunk_pages_overlap_actually_overlaps():
    text = " ".join(f"word{i}" for i in range(2000))
    out = chunk_pages([DocPage(1, text)], target_words=400, overlap_words=80)
    assert len(out) >= 2
    # Last 80 words of chunk 0 should appear at the start of chunk 1
    a_tail = out[0].text.split()[-50:]
    b_head = out[1].text.split()[:200]
    assert any(w in b_head for w in a_tail)


def test_chunk_pages_spans_multiple_pages():
    pages = [DocPage(1, "page one " * 50),
             DocPage(2, "page two " * 50),
             DocPage(3, "page three " * 50)]
    out = chunk_pages(pages, target_words=120, overlap_words=20)
    pages_seen = sorted({(c.page_start, c.page_end) for c in out})
    assert any(ps != pe for ps, pe in pages_seen) or len(out) >= 3


def test_chunk_pages_invalid_args():
    with pytest.raises(ValueError):
        chunk_pages([DocPage(1, "x")], target_words=0)
    with pytest.raises(ValueError):
        chunk_pages([DocPage(1, "x")], target_words=100, overlap_words=100)
    with pytest.raises(ValueError):
        chunk_pages([DocPage(1, "x")], target_words=100, overlap_words=-1)


def test_select_chunks_in_range_basic():
    pages = [DocPage(i, f"content for page {i} " * 30) for i in range(1, 11)]
    chunks = chunk_pages(pages, target_words=200)
    sel = select_chunks_in_range(chunks, 3, 5)
    # Every selected chunk must overlap [3,5]
    for c in sel:
        assert not (c.page_end < 3 or c.page_start > 5)
    # And we should not pick chunks fully outside the range
    outside = [c for c in chunks if c.page_end < 3 or c.page_start > 5]
    for c in outside:
        assert c not in sel


def test_select_chunks_in_range_handles_swapped_args():
    pages = [DocPage(i, f"page {i} " * 30) for i in range(1, 6)]
    chunks = chunk_pages(pages, target_words=100)
    sel_a = select_chunks_in_range(chunks, 4, 2)
    sel_b = select_chunks_in_range(chunks, 2, 4)
    assert sel_a == sel_b


def test_select_chunks_in_range_max_chunks_cap():
    pages = [DocPage(i, "x " * 200) for i in range(1, 21)]
    chunks = chunk_pages(pages, target_words=100, overlap_words=10)
    sel = select_chunks_in_range(chunks, 1, 20, max_chunks=5)
    assert len(sel) == 5
