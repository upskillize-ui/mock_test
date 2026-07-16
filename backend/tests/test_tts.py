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

# The two roster voices, resolved once. Tests that care about a SPECIFIC field build
# their own Voice; everything else just needs "a female voice" / "a male voice".
NIA = t.Voice(speaker="ritu", pace=0.93)
NOVA = t.Voice(speaker="shubh", pace=1.0)


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
    a = t.cache_key("Tell me about yourself.", NIA)
    b = t.cache_key("Tell me about yourself.", NIA)
    assert a == b
    assert len(a) == 64 and all(c in "0123456789abcdef" for c in a)


def test_cache_key_varies_by_speaker_and_text():
    base = t.cache_key("Tell me about yourself.", NIA)
    assert base != t.cache_key("Tell me about yourself.", NOVA)   # speaker matters
    assert base != t.cache_key("Tell me about your projects.", NIA)  # text matters


def test_cache_key_ignores_markdown_noise():
    # Two inputs that preprocess to the same speech share a cache entry.
    plain = t.cache_key("Explain your EMI strategy.", NIA)
    marked = t.cache_key("Explain your **EMI** strategy.", NIA)
    assert plain == marked


def test_cache_key_varies_by_pace_at_the_same_speaker():
    """Re-pacing Nia MUST bust her cache.

    The regression this pins: pace used to be read inside cache_key from the global
    settings.TTS_PACE while the payload sent a per-voice pace. Retuning NIA_PACE would
    then have kept serving the OLD read from disk — the config knob would appear dead.
    Same speaker, different pace, therefore: different key.
    """
    slow = t.cache_key("Walk me through it.", t.Voice(speaker="ritu", pace=0.93))
    fast = t.cache_key("Walk me through it.", t.Voice(speaker="ritu", pace=1.0))
    assert slow != fast


def test_cache_key_covers_every_voice_field():
    """The Voice contract: every field that reaches the vendor is hashed into the key.

    Enforced structurally rather than by eye. Add a field to Voice that changes the audio
    and forget cache_fields(), and this fails — instead of shipping a cache that silently
    serves audio from settings nobody is running any more.
    """
    import dataclasses

    base = t.Voice(speaker="ritu", pace=0.93)
    base_key = t.cache_key("Same words either way.", base)
    # A deliberately different value per field type; each must move the key on its own.
    bumped = {"speaker": "priya", "pace": 0.75}

    for field in dataclasses.fields(t.Voice):
        assert field.name in bumped, (
            f"Voice.{field.name} is new: give it a distinct test value here, and make sure "
            f"cache_fields() includes it — an unhashed field means stale audio."
        )
        variant = dataclasses.replace(base, **{field.name: bumped[field.name]})
        assert t.cache_key("Same words either way.", variant) != base_key, (
            f"Voice.{field.name} changes the audio but not the cache key — "
            f"add it to Voice.cache_fields()."
        )


# ── Graceful None on vendor failure ─────────────────────────────────────────

def test_synthesize_none_without_api_key():
    old = t.settings.SARVAM_API_KEY
    t.settings.SARVAM_API_KEY = ""
    try:
        assert asyncio.run(t.synthesize("hello", NIA)) is None
    finally:
        t.settings.SARVAM_API_KEY = old


def test_get_audio_hash_none_when_synth_fails(monkeypatch=None):
    # Force the vendor call to fail; get_audio_hash must return None, never raise.
    async def _fail(text, speaker):
        return None
    orig = t.synthesize
    t.synthesize = _fail
    try:
        res = asyncio.run(t.get_audio_hash("sess-fail", "a unique never-cached prompt", NIA))
        assert res is None
    finally:
        t.synthesize = orig


def test_cost_guard_blocks_after_cap():
    # At/over the per-session cap, no vendor call is attempted -> None.
    sid = "sess-capped"
    t._session_synth_counts[sid] = t._tts_cap()
    try:
        res = asyncio.run(t.get_audio_hash(sid, "brand new uncached question xyz", NIA))
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
        k1 = asyncio.run(t.get_audio_hash(sid, "a fresh cacheable question 42", NIA))
        k2 = asyncio.run(t.get_audio_hash(sid, "a fresh cacheable question 42", NIA))
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


# ── The cost meter: the sentence-split is billed in SECONDS, so measure seconds ──

def _mp3(seconds: float) -> bytes:
    """A synthetic CBR MPEG1 Layer III clip of a known duration.

    Header FF FB 90 00 = MPEG1 / Layer III / 128 kbps / 44.1 kHz, so 16 000 bytes is
    exactly one second of audio and the duration maths is checkable by hand.
    """
    return b"\xff\xfb\x90\x00" + b"\x00" * (int(16_000 * seconds) - 4)


def test_mp3_duration_is_measured_from_the_frame_header():
    assert t.mp3_duration_seconds(_mp3(1)) == 1.0
    assert t.mp3_duration_seconds(_mp3(3.5)) == 3.5
    # An ID3 tag in front must not be counted as audio.
    tagged = b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10 + _mp3(2)
    assert t.mp3_duration_seconds(tagged) == 2.0


def test_an_unparseable_clip_is_never_a_crash_and_never_a_guess():
    for junk in (b"", b"not-audio", None, b"\x00" * 50):
        assert t.mp3_duration_seconds(junk) is None


def test_the_meter_separates_what_we_paid_for_from_what_the_cache_gave_us():
    async def _fake(text, speaker):
        return _mp3(4)                      # every clip is 4 seconds of audio
    orig = t.synthesize
    t.synthesize = _fake
    sid = "sess-meter"
    t._session_synth_counts.pop(sid, None)
    t._session_seconds.pop(sid, None)
    keys = []
    try:
        # Two DIFFERENT sentences (the E2 split), then a repeat of the first — which is
        # exactly the shape of a real session: unique questions, repeated greetings.
        keys.append(asyncio.run(t.get_audio_hash(sid, "meter sentence one", NIA)))
        keys.append(asyncio.run(t.get_audio_hash(sid, "meter sentence two", NIA)))
        asyncio.run(t.get_audio_hash(sid, "meter sentence one", NIA))

        cost = t.session_cost(sid)
        assert cost["vendor_calls"] == 2          # only the two we actually bought
        assert cost["vendor_seconds"] == 8.0      # ...and THAT is the billable number
        assert cost["cache_hits"] == 1
        assert cost["cached_seconds"] == 4.0      # what the cache saved us
        assert cost["total_seconds"] == 12.0
        assert cost["cache_saved_pct"] == 33
        assert cost["unmeasured_clips"] == 0
    finally:
        t.synthesize = orig
        for k in keys:
            try:
                t.cache_path(k).unlink()
            except Exception:
                pass
        t._session_synth_counts.pop(sid, None)
        t._session_seconds.pop(sid, None)


def test_the_meter_reads_zero_for_a_session_that_synthesised_nothing():
    cost = t.session_cost("sess-never-spoke")
    assert cost["vendor_seconds"] == 0.0
    assert cost["total_seconds"] == 0.0
    assert cost["cache_saved_pct"] == 0          # no division by zero
    t._session_seconds.pop("sess-never-spoke", None)


def test_an_unparseable_clip_is_counted_but_not_invented():
    async def _fake(text, speaker):
        return b"definitely-not-an-mp3"
    orig = t.synthesize
    t.synthesize = _fake
    sid = "sess-unmeasured"
    t._session_synth_counts.pop(sid, None)
    t._session_seconds.pop(sid, None)
    try:
        k = asyncio.run(t.get_audio_hash(sid, "an unmeasurable clip", NIA))
        cost = t.session_cost(sid)
        assert cost["vendor_calls"] == 1         # we still paid for it
        assert cost["vendor_seconds"] == 0.0     # but we do not make a number up
        assert cost["unmeasured_clips"] == 1     # we say so instead
    finally:
        t.synthesize = orig
        try:
            t.cache_path(k).unlink()
        except Exception:
            pass
        t._session_synth_counts.pop(sid, None)
        t._session_seconds.pop(sid, None)


# ── The 2-call lever: a reply is synthesised ONCE, as its sentences ─────────

def test_a_reply_is_billed_once_per_sentence_and_not_once_more_for_the_whole():
    """The lever, pinned. We used to synthesise a reply BOTH whole and split — the same
    audio, billed twice, and the whole clip was almost never played. A 3-sentence reply
    must cost exactly 3 clips."""
    import asyncio as _aio
    from app import main as m

    calls = []
    async def _fake_hash(session_id, text, speaker):
        calls.append(text)
        return "a" * 64
    orig = t.get_audio_hash
    t.get_audio_hash = _fake_hash
    try:
        segs = _aio.run(m._try_tts_segments("sess", "First line. Second line. And the question?", "female"))
        assert len(segs) == 3
        assert len(calls) == 3          # NOT 4 — there is no whole-reply clip any more
        assert [s["text"] for s in segs] == ["First line.", "Second line.", "And the question?"]
    finally:
        t.get_audio_hash = orig


def test_the_response_no_longer_carries_a_whole_reply_audio_url():
    # Re-adding this field is how the duplicate bill would creep back: the client would
    # have something to prefer over the segments again. Make it a deliberate act.
    from app.schemas import StartSessionResponse, TurnResponse
    assert "audio_url" not in TurnResponse.model_fields
    assert "audio_url" not in StartSessionResponse.model_fields
    # The short one-off lines DO still carry one clip each — they have no sentences to
    # split and are one line by nature.
    assert "rating_audio_url" in TurnResponse.model_fields
    from app.schemas import ReaskResponse
    assert "audio_url" in ReaskResponse.model_fields


# ── Bulbul v3 upgrade: payload params + cache-key versioning ────────────────

def test_v3_payload_params():
    p = t.build_payload("Explain FOIR to me.", NIA)
    assert p["model"] == "bulbul:v3"
    assert p["speaker"] == "ritu"
    assert p["output_audio_codec"] == "mp3"
    assert p["speech_sample_rate"] == 44100
    assert p["temperature"] == 0.4
    assert p["pace"] == 0.93          # NIA's own pace — pace is per-voice, not global
    # v3 does NOT accept pitch/loudness — they must never be sent.
    assert "pitch" not in p and "loudness" not in p


def test_dict_id_only_when_configured():
    # Absent by default.
    assert "dict_id" not in t.build_payload("hi", NIA)
    old = t.settings.TTS_DICT_ID
    t.settings.TTS_DICT_ID = "bfsi-terms-v1"
    try:
        assert t.build_payload("hi", NIA)["dict_id"] == "bfsi-terms-v1"
    finally:
        t.settings.TTS_DICT_ID = old


def test_cache_key_varies_by_model_and_sample_rate():
    # A model/sample-rate change MUST change the key so stale v2 audio can't serve.
    base = t.cache_key("Tell me about yourself.", NIA)
    old_model, old_sr = t.settings.TTS_MODEL, t.settings.TTS_SAMPLE_RATE
    try:
        t.settings.TTS_MODEL = "bulbul:v2"
        assert t.cache_key("Tell me about yourself.", NIA) != base   # model matters
        t.settings.TTS_MODEL = old_model
        t.settings.TTS_SAMPLE_RATE = 22050
        assert t.cache_key("Tell me about yourself.", NIA) != base   # sample rate matters
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
