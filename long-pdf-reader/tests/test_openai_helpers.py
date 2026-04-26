"""Tests for OpenAI helpers using a fake client. No real API calls."""
from types import SimpleNamespace
from typing import List

import pytest

from pdf_utils import (
    OpenAICallError,
    TextChunk,
    answer_with_citations,
    cosine_similarity,
    embed_texts,
    split_for_tts,
    summarize_chunks,
    top_k_chunks,
    tts_clip,
)


# --- Fakes ---------------------------------------------------------------

class _FakeEmbeddings:
    def __init__(self, dim=8, fail_times=0, fail_with=None):
        self.dim = dim
        self.calls = 0
        self.fail_times = fail_times
        self.fail_with = fail_with or RuntimeError("rate limit exceeded")

    def create(self, model, input):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.fail_with
        data = []
        for s in input:
            h = sum(ord(c) for c in s)
            vec = [(h + i) % 7 / 7.0 for i in range(self.dim)]
            data.append(SimpleNamespace(embedding=vec))
        return SimpleNamespace(data=data)


class _FakeChatCompletions:
    def __init__(self, outer):
        self.outer = outer
    def create(self, model, messages, temperature=0.0, **kw):
        self.outer.last_messages = messages
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.outer.reply))])


class _FakeChat:
    def __init__(self, reply="Hello (p. 1)."):
        self.reply = reply
        self.last_messages = None
        self.completions = _FakeChatCompletions(self)


class _FakeAudioSpeech:
    def __init__(self, payload=b"ID3FAKE-MP3"):
        self.payload = payload
        self.last_kwargs = None
    def create(self, **kw):
        self.last_kwargs = kw
        return SimpleNamespace(read=lambda: self.payload)


class _FakeAudio:
    def __init__(self, payload=b"ID3FAKE-MP3"):
        self.speech = _FakeAudioSpeech(payload)


class FakeClient:
    def __init__(self, *, fail_times=0, fail_with=None,
                 reply="Hello (p. 1).", audio_payload=b"ID3FAKE"):
        self.embeddings = _FakeEmbeddings(fail_times=fail_times,
                                          fail_with=fail_with)
        self.chat = _FakeChat(reply=reply)
        self.audio = _FakeAudio(payload=audio_payload)


# --- cosine + top-k -------------------------------------------------------

def test_cosine_similarity_basic():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_similarity_edge_cases():
    assert cosine_similarity([], [1, 2]) == 0.0
    assert cosine_similarity([0, 0], [1, 1]) == 0.0
    assert cosine_similarity([1, 2, 3], [1, 2]) == 0.0  # mismatched dims


def test_top_k_chunks_orders_by_similarity():
    chunks = [
        TextChunk(0, 1, 1, "a", embedding=[1.0, 0.0]),
        TextChunk(1, 2, 2, "b", embedding=[0.0, 1.0]),
        TextChunk(2, 3, 3, "c", embedding=[0.9, 0.1]),
    ]
    out = top_k_chunks([1.0, 0.0], chunks, k=2)
    assert len(out) == 2
    assert out[0][1].chunk_id == 0
    assert out[1][1].chunk_id == 2


def test_top_k_chunks_skips_unembedded():
    chunks = [TextChunk(0, 1, 1, "a"),
              TextChunk(1, 2, 2, "b", embedding=[1.0, 0.0])]
    out = top_k_chunks([1.0, 0.0], chunks, k=5)
    assert len(out) == 1
    assert out[0][1].chunk_id == 1


# --- embed_texts ----------------------------------------------------------

def test_embed_texts_empty_returns_empty():
    assert embed_texts(FakeClient(), []) == []


def test_embed_texts_returns_one_vector_per_input():
    client = FakeClient()
    out = embed_texts(client, ["hello", "world", "foo"], batch_size=2)
    assert len(out) == 3
    assert all(isinstance(v, list) and len(v) == 8 for v in out)


def test_embed_texts_uses_progress_callback():
    client = FakeClient()
    seen = []
    def cb(done, total):
        seen.append((done, total))
    embed_texts(client, ["a", "b", "c", "d", "e"], batch_size=2,
                progress_cb=cb)
    assert seen
    assert seen[-1][0] >= seen[-1][1]  # final call reaches/exceeds total


def test_embed_texts_retries_transient_then_succeeds(monkeypatch):
    # Don't actually sleep during retries
    import pdf_utils
    monkeypatch.setattr(pdf_utils.time, "sleep", lambda s: None)
    client = FakeClient(fail_times=2,
                        fail_with=RuntimeError("rate limit 429"))
    out = embed_texts(client, ["x"])
    assert len(out) == 1
    assert client.embeddings.calls == 3  # 2 failures + 1 success


def test_embed_texts_does_not_retry_auth_errors(monkeypatch):
    import pdf_utils
    monkeypatch.setattr(pdf_utils.time, "sleep", lambda s: None)
    client = FakeClient(fail_times=99,
                        fail_with=RuntimeError("Invalid API key (401)"))
    with pytest.raises(OpenAICallError) as exc:
        embed_texts(client, ["x"])
    assert "API key" in exc.value.user_message
    assert client.embeddings.calls == 1  # no retry


def test_embed_texts_gives_up_after_max_retries(monkeypatch):
    import pdf_utils
    monkeypatch.setattr(pdf_utils.time, "sleep", lambda s: None)
    client = FakeClient(fail_times=99,
                        fail_with=RuntimeError("connection timeout"))
    with pytest.raises(OpenAICallError) as exc:
        embed_texts(client, ["x"])
    assert "timeout" in exc.value.user_message.lower() or \
           "network" in exc.value.user_message.lower()


# --- answer + summarize ---------------------------------------------------

def test_answer_with_citations_handles_empty_question():
    out = answer_with_citations(FakeClient(), "   ", [])
    assert "question" in out.lower()


def test_answer_with_citations_handles_no_results():
    out = answer_with_citations(FakeClient(), "what is X?", [])
    assert "could not find" in out.lower()


def test_answer_with_citations_passes_context_to_chat():
    client = FakeClient(reply="Answer here (p. 7).")
    chunks = [
        (0.9, TextChunk(1, 7, 7, "Important content about X.",
                        embedding=[1.0])),
        (0.7, TextChunk(2, 8, 9, "More detail on X.",
                        embedding=[1.0])),
    ]
    out = answer_with_citations(client, "What is X?", chunks)
    assert out == "Answer here (p. 7)."
    user_msg = client.chat.last_messages[-1]["content"]
    assert "page 7" in user_msg
    assert "What is X?" in user_msg


def test_summarize_chunks_empty():
    assert summarize_chunks(FakeClient(), [], "Short summary") == \
        "Nothing to summarize."


def test_summarize_chunks_includes_page_labels():
    client = FakeClient(reply="Done.")
    chunks = [TextChunk(1, 2, 4, "Some text from pages 2 to 4.")]
    summarize_chunks(client, chunks, "Short summary")
    assert "pages 2" in client.chat.last_messages[-1]["content"]


# --- TTS ------------------------------------------------------------------

def test_split_for_tts_empty():
    assert split_for_tts("") == []
    assert split_for_tts("   ") == []


def test_split_for_tts_short_returns_one():
    out = split_for_tts("Just one short paragraph.")
    assert len(out) == 1


def test_split_for_tts_long_text_splits_under_limit():
    long_text = ("This is a sentence. " * 500)  # ~10k chars
    parts = split_for_tts(long_text, max_chars=2000)
    assert len(parts) >= 5
    assert all(len(p) <= 2000 for p in parts)
    # No part is empty
    assert all(p.strip() for p in parts)


def test_split_for_tts_respects_paragraph_boundaries():
    text = "Paragraph one is short.\n\nParagraph two is also short."
    # 53 chars total; force a split with a tighter cap.
    parts = split_for_tts(text, max_chars=30)
    assert len(parts) == 2
    assert "one" in parts[0] and "two" in parts[1]


def test_tts_clip_returns_bytes():
    client = FakeClient(audio_payload=b"FAKE-MP3-BYTES")
    out = tts_clip(client, "Hello world", voice="alloy",
                   instructions="Read warmly.")
    assert out == b"FAKE-MP3-BYTES"
    assert client.audio.speech.last_kwargs["voice"] == "alloy"
    assert client.audio.speech.last_kwargs["response_format"] == "mp3"
    assert client.audio.speech.last_kwargs["instructions"] == "Read warmly."


def test_tts_clip_rejects_empty_text():
    with pytest.raises(ValueError):
        tts_clip(FakeClient(), "")
    with pytest.raises(ValueError):
        tts_clip(FakeClient(), "   ")
