"""Unit tests for Voice Phase 1 TTS logic (app/tts.py).

Pure/offline: acronym + markdown preprocessing, cache-key stability, and graceful
None on vendor failure. No real Sarvam calls — the vendor path is monkeypatched.

Runnable with either:  python -m pytest tests/test_tts.py
                  or:  python tests/test_tts.py
"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")
# Isolated cache dir so tests never touch a real one.
os.environ.setdefault("TTS_CACHE_DIR", os.path.join(tempfile.gettempdir(), "iq_tts_test_cache"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import tts as t  # noqa: E402


# ── Preprocessing: acronyms + markdown ──────────────────────────────────────

def test_acronyms_expanded():
    out = t.preprocess("Your CIBIL and NPA affect EMI, KYC, FOIR, CAGR and DSCR.")
    assert "sibil" in out
    assert "N P A" in out
    assert "E M I" in out
    assert "K Y C" in out
    assert "F O I R" in out
    assert "C A G R" in out
    assert "D S C R" in out
    # The raw uppercase tokens should be gone.
    assert "CIBIL" not in out and "NPA" not in out


def test_acronyms_whole_word_and_case_sensitive():
    # Lowercase look-alikes and embedded substrings must NOT be expanded.
    out = t.preprocess("the kyc word and emitter and premium")
    assert "kyc" in out            # lowercase untouched
    assert "emitter" in out        # 'EMI' substring inside a word untouched
    assert "E M I" not in out


def test_markdown_stripped():
    out = t.preprocess("**Bold** and *italic* with `code` and [a link](http://x.com)\n# Heading")
    for junk in ("**", "*", "`", "[", "](", "#"):
        assert junk not in out
    assert "Bold" in out and "italic" in out and "link" in out and "Heading" in out


# ── Cache-key stability ─────────────────────────────────────────────────────

def test_cache_key_stable_and_deterministic():
    a = t.cache_key("Tell me about yourself.", "ritu")
    b = t.cache_key("Tell me about yourself.", "ritu")
    assert a == b
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)


def test_cache_key_varies_by_speaker_and_text():
    base = t.cache_key("Tell me about yourself.", "ritu")
    assert base != t.cache_key("Tell me about yourself.", "shubh")   # speaker matters
    assert base != t.cache_key("Tell me about your projects.", "ritu")  # text matters


def test_cache_key_ignores_markdown_noise():
    # Two inputs that preprocess to the same speech share a cache entry.
    plain = t.cache_key("Explain your EMI strategy.", "ritu")
    marked = t.cache_key("Explain your **EMI** strategy.", "ritu")
    assert plain == marked


# ── Graceful None on vendor failure ─────────────────────────────────────────

def test_synthesize_none_without_api_key():
    old = t.settings.SARVAM_API_KEY
    t.settings.SARVAM_API_KEY = ""
    try:
        assert asyncio.run(t.synthesize("hello", "ritu")) is None
    finally:
        t.settings.SARVAM_API_KEY = old


def test_get_audio_hash_none_when_synth_fails(monkeypatch=None):
    # Force the vendor call to fail; get_audio_hash must return None, never raise.
    async def _fail(text, speaker):
        return None
    orig = t.synthesize
    t.synthesize = _fail
    try:
        res = asyncio.run(t.get_audio_hash("sess-fail", "a unique never-cached prompt", "ritu"))
        assert res is None
    finally:
        t.synthesize = orig


def test_cost_guard_blocks_after_cap():
    # At/over the per-session cap, no vendor call is attempted -> None.
    sid = "sess-capped"
    t._session_synth_counts[sid] = t._tts_cap()
    try:
        res = asyncio.run(t.get_audio_hash(sid, "brand new uncached question xyz", "ritu"))
        assert res is None
    finally:
        t._session_synth_counts.pop(sid, None)


def test_cache_hit_does_not_recall_vendor():
    # First call synthesizes (mocked) and caches; second call is a cache hit and
    # must NOT increment the vendor counter.
    calls = {"n": 0}
    async def _fake(text, speaker):
        calls["n"] += 1
        return b"ID3fake-mp3-bytes"
    orig = t.synthesize
    t.synthesize = _fake
    sid = "sess-cache"
    t._session_synth_counts.pop(sid, None)
    try:
        k1 = asyncio.run(t.get_audio_hash(sid, "a fresh cacheable question 42", "ritu"))
        k2 = asyncio.run(t.get_audio_hash(sid, "a fresh cacheable question 42", "ritu"))
        assert k1 == k2 and k1 is not None
        assert calls["n"] == 1                       # vendor hit only once
        assert t._session_synth_counts[sid] == 1     # counter incremented once
        assert t.read_cache(k1) is not None          # cached bytes present
    finally:
        t.synthesize = orig
        try:
            t.cache_path(k1).unlink()
        except Exception:
            pass
        t._session_synth_counts.pop(sid, None)


# ── Bulbul v3 upgrade: payload params + cache-key versioning ────────────────

def test_v3_payload_params():
    p = t.build_payload("Explain FOIR to me.", "ritu")
    assert p["model"] == "bulbul:v3"
    assert p["speaker"] == "ritu"
    assert p["output_audio_codec"] == "mp3"
    assert p["speech_sample_rate"] == 44100
    assert p["temperature"] == 0.4
    assert p["pace"] == 1.0
    # v3 does NOT accept pitch/loudness — they must never be sent.
    assert "pitch" not in p and "loudness" not in p


def test_dict_id_only_when_configured():
    # Absent by default.
    assert "dict_id" not in t.build_payload("hi", "ritu")
    old = t.settings.TTS_DICT_ID
    t.settings.TTS_DICT_ID = "bfsi-terms-v1"
    try:
        assert t.build_payload("hi", "ritu")["dict_id"] == "bfsi-terms-v1"
    finally:
        t.settings.TTS_DICT_ID = old


def test_cache_key_varies_by_model_and_sample_rate():
    # A model/sample-rate change MUST change the key so stale v2 audio can't serve.
    base = t.cache_key("Tell me about yourself.", "ritu")
    old_model, old_sr = t.settings.TTS_MODEL, t.settings.TTS_SAMPLE_RATE
    try:
        t.settings.TTS_MODEL = "bulbul:v2"
        assert t.cache_key("Tell me about yourself.", "ritu") != base   # model matters
        t.settings.TTS_MODEL = old_model
        t.settings.TTS_SAMPLE_RATE = 22050
        assert t.cache_key("Tell me about yourself.", "ritu") != base   # sample rate matters
    finally:
        t.settings.TTS_MODEL, t.settings.TTS_SAMPLE_RATE = old_model, old_sr


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
