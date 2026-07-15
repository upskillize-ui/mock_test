"""FAST START + the realism pack's clip cache.

The founder's complaint was one sentence long: the loading spinner is too long. Measured,
it was 14.5 seconds from clicking "Start interview" to hearing the first word — and every
one of those seconds was self-inflicted. /session/start was doing three things at once:
writing a session row (fast), calling an LLM to improvise a greeting (slow), and waiting
for EVERY sentence of that greeting to be read aloud by a vendor (slower still). Nothing
about a session row needs an LLM, and nothing about the first spoken word needs sentence
four to have been synthesised.

So the room now renders on the session row, and the greeting streams in behind it.

Runnable with:  python -m pytest tests/test_fast_start.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio  # noqa: E402

import pytest  # noqa: E402

from app import main as m  # noqa: E402
from app import tts  # noqa: E402
from app.config import settings  # noqa: E402
from app.schemas import SpeechRequest, GreetingRequest  # noqa: E402


GREETING = "Asha, good to meet you. I run credit risk here. Walk me through how you'd size a portfolio's expected loss."


@pytest.fixture
def fake_tts(monkeypatch):
    """Count the synth calls, without touching the vendor. The number of clips we AWAIT
    before the first word can be spoken is the whole point of this change."""
    calls = []

    async def _synth(session_id, text_out, voice):
        calls.append(text_out)
        return f"/session/audio/{'a' * 64}"

    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(m, "_try_tts", _synth)
    return calls


# ── The lever: we await ONE clip, not all of them ────────────────────────────

def test_first_only_synthesises_exactly_one_clip(fake_tts):
    segs = asyncio.run(m._try_tts_segments("s1", GREETING, "female", first_only=True))

    assert len(segs) == 3                     # three sentences...
    assert len(fake_tts) == 1                 # ...and we waited for exactly ONE of them.
    assert fake_tts[0] == "Asha, good to meet you."

    # Sentence one can be SPOKEN. The rest are on their way, and say so.
    assert segs[0]["audio_url"] and segs[0]["pending"] is False
    for seg in segs[1:]:
        assert seg["audio_url"] is None
        assert seg["pending"] is True         # "its audio is coming — wait for it"
        assert seg["text"]                    # the caption is already there


def test_pending_is_not_the_same_as_failed(fake_tts):
    """A null audio_url with `pending` means 'coming'. A null audio_url WITHOUT it means
    the synth failed and the client should show the caption for a beat and move on. The
    client behaves differently in each case, so the two must not be conflated."""
    segs = asyncio.run(m._try_tts_segments("s1", GREETING, "female", first_only=False))
    assert len(fake_tts) == 3                 # the old behaviour: await every sentence
    for seg in segs:
        assert seg["pending"] is False


def test_the_full_greeting_still_comes_back_so_the_captions_are_complete(fake_tts):
    segs = asyncio.run(m._try_tts_segments("s1", GREETING, "female", first_only=True))
    spoken = " ".join(s["text"] for s in segs)
    # Nothing is dropped — only the WAITING is dropped.
    assert "expected loss" in spoken
    assert tts.split_sentences(GREETING) == [s["text"] for s in segs]


# ── /session/speech: an index, never text ────────────────────────────────────

def test_the_speech_endpoint_takes_an_index_and_refuses_free_text():
    """This is the whole security story for the second half of the greeting. The client
    cannot hand us a string and have us bill Sarvam to read it aloud: it sends an INDEX,
    and the server re-derives the sentence from the reply it already stored."""
    req = SpeechRequest(session_id="s1", voice="female", from_index=1)
    assert req.from_index == 1
    assert not hasattr(req, "text")

    # The index is bounded — a client cannot ask for sentence 10,000 of anything.
    with pytest.raises(Exception):
        SpeechRequest(session_id="s1", from_index=-1)
    with pytest.raises(Exception):
        SpeechRequest(session_id="s1", from_index=999)


def test_speech_defaults_to_the_sentence_after_the_one_already_playing():
    assert SpeechRequest(session_id="s1").from_index == 1


def test_the_greeting_request_is_just_a_session_and_a_voice():
    g = GreetingRequest(session_id="s1", voice="male")
    assert g.session_id == "s1" and g.voice == "male"
    assert GreetingRequest(session_id="s1").voice == "female"


# ── QUESTION CADENCE: a person absorbs an answer before firing the next one ──

def test_the_beat_before_a_question_lengthens_after_a_real_answer(fake_tts):
    reply = "Right, so you'd hold the tail. Now tell me how you'd price it."
    after_answer = asyncio.run(m._try_tts_segments(
        "s1", reply, "female", first_only=True,
        pre_question_pause_ms=m.PRE_QUESTION_PAUSE_SUBSTANTIVE_MS))
    after_skip = asyncio.run(m._try_tts_segments(
        "s1", reply, "female", first_only=True,
        pre_question_pause_ms=m.PRE_QUESTION_PAUSE_MS))

    # The pause sits before the QUESTION — the last sentence.
    assert after_answer[-1]["pause_before_ms"] == m.PRE_QUESTION_PAUSE_SUBSTANTIVE_MS
    assert after_skip[-1]["pause_before_ms"] == m.PRE_QUESTION_PAUSE_MS
    assert after_answer[-1]["pause_before_ms"] > after_skip[-1]["pause_before_ms"]


def test_the_cadence_numbers_are_the_ones_the_spec_asked_for():
    assert m.PRE_QUESTION_PAUSE_MS == 700                          # after a skip: unchanged
    assert 1000 <= m.PRE_QUESTION_PAUSE_SUBSTANTIVE_MS <= 1200     # after a real answer
    assert 300 <= m.INTER_SENTENCE_PAUSE_MS <= 450                 # between sentences


# ── Reading the opening out of a HALF-WRITTEN JSON stream ───────────────────
# This is the lever that actually bought the last four seconds: the kickoff streams,
# `opening` is the first key in it, and the interviewer's first sentence therefore exists
# about a fifth of the way through the generation. We send it to the voice vendor there and
# then, so the synthesis runs alongside the writing instead of queueing behind it.

from app.prompts import partial_opening, first_complete_sentence  # noqa: E402

KICKOFF = (
    '{\n  "opening": "Hi Asha, I\'m Riya. I run credit risk here. '
    'Walk me through how you would size expected loss on an unsecured book.",\n'
    '  "identity": "brisk, forensic, opens on trade-offs"\n}'
)


def _stream(raw):
    """Every prefix of the response, the way the deltas actually arrive."""
    return (raw[:i] for i in range(1, len(raw) + 1))


def test_the_first_sentence_is_readable_long_before_the_model_has_finished():
    fired_at = fired = None
    for i, prefix in enumerate(_stream(KICKOFF), start=1):
        s = first_complete_sentence(partial_opening(prefix))
        if s:
            fired_at, fired = i, s
            break

    assert fired == "Hi Asha, I'm Riya."
    # ...and it landed in the first quarter of the stream. That headroom IS the fix: the
    # 1.8s of vendor synthesis now runs underneath the remaining seconds of generation.
    assert fired_at / len(KICKOFF) < 0.25


def test_the_early_clip_is_exactly_the_clip_the_finished_greeting_asks_for():
    """If these differed, the interviewer would open with a sentence she does not go on to
    say. They cannot: a model cannot un-write a sentence it has moved past, and both sides
    split with the same tts.split_sentences."""
    import json
    opening = json.loads(KICKOFF)["opening"]
    early = first_complete_sentence(partial_opening(KICKOFF))
    assert early == tts.split_sentences(opening)[0]


def test_a_half_written_sentence_is_never_synthesised():
    """We only spend a vendor call on a sentence the model has FINISHED — a sentence with
    no terminal punctuation is one it may still be adding words to."""
    assert first_complete_sentence(partial_opening('{"opening": "Hi Asha, I am')) == ""
    assert first_complete_sentence(partial_opening('{"opening": "')) == ""
    assert first_complete_sentence(partial_opening('{"open')) == ""
    assert first_complete_sentence(partial_opening("")) == ""
    assert first_complete_sentence("") == ""


def test_the_scan_survives_the_escapes_a_real_greeting_contains():
    # A quoted phrase in the opening.
    assert partial_opening(r'{"opening": "She said \"go\". Then') == 'She said "go". Then'
    # A unicode escape (a name, a rupee sign, an accented word).
    assert partial_opening(r'{"opening": "café. Next') == "café. Next"
    # An ESCAPED backslash is a backslash.
    assert partial_opening('{"opening": "a' + "\\\\" + 'b') == "a\\b"


def test_an_escape_that_is_still_arriving_is_not_half_decoded():
    """Deltas land mid-token. A lone trailing backslash — or half a \\uXXXX — is an escape
    whose second half has not been written yet, and we must stop cleanly at it rather than
    emit a stray character into a sentence we are about to have read aloud."""
    # A lone trailing backslash: the escape's second half is still in flight.
    assert partial_opening('{"opening": "done. ' + "\\") == "done. "
    # Half a unicode escape.
    assert partial_opening(r'{"opening": "done. \u00') == "done. "
    # Neither case loses the sentence that HAD landed — which is the one we care about.
    assert first_complete_sentence(partial_opening('{"opening": "done. ' + "\\")) == "done."


def test_the_closing_quote_ends_the_field_and_the_identity_is_not_swallowed():
    got = partial_opening(KICKOFF)
    assert got.endswith("unsecured book.")
    assert "brisk" not in got and "forensic" not in got


def test_it_still_works_if_the_model_ignores_us_and_writes_identity_first():
    """The key ORDER is an optimisation, not a contract. A model that puts identity first
    costs us the head start — it must not cost us the greeting."""
    raw = '{"identity": "warm, unhurried", "opening": "Hello Asha. Why credit risk?"}'
    assert first_complete_sentence(partial_opening(raw)) == "Hello Asha."


# ── The clip pack (acknowledgments + backchannels) ───────────────────────────

def test_the_ack_pack_is_the_eight_lines_the_spec_named():
    assert len(tts.ACK_LINES) == 8
    for line in ("Hmm.", "Okay.", "Right.", "Accha.", "Got it.",
                 "Interesting.", "Let me think about that.", "Mm-hmm."):
        assert line in tts.ACK_LINES


def test_the_acks_rotate_on_a_seed_so_a_session_never_loops_one_line():
    lines = [tts.ack_line(i) for i in range(8)]
    assert len(set(lines)) == 8                 # a full rotation before any repeat
    assert tts.ack_line(0) == tts.ack_line(8)   # stable: the same seed, the same clip
    assert tts.ack_line(-3) == tts.ack_line(3)  # and it never indexes out of range


def test_the_clip_pack_is_deduplicated_on_disk():
    """Both backchannel lines ("Mm-hmm.", "Right.") are ALSO acknowledgments. The cache is
    content-addressed, so they were always going to be one clip each — the pack is 8 clips
    per voice, 16 in total, for the life of the product."""
    lines = tts.clip_pack_lines()
    assert len(lines) == len(set(lines))
    assert len(lines) == 8                       # 8 acks + 2 backchannels, both shared
    assert set(tts.BACKCHANNEL_LINES) <= set(tts.ACK_LINES)
    assert set(tts.BACKCHANNEL_LINES) <= set(lines)


def test_the_shared_clips_are_not_billed_to_whoever_happened_to_warm_them(monkeypatch):
    """The ack pack belongs to the PRODUCT, not to a session. Metering twenty clips against
    the first candidate to open the app would make the per-session cost meter lie — and
    that meter is what the Sarvam credits application is built on."""
    monkeypatch.setattr(tts, "read_cache", lambda k: b"\xff\xfb\x90\x00" + b"\x00" * 900)
    before = tts.session_cost("s-shared")

    key = asyncio.run(tts.get_shared_audio_hash("Hmm.", "ritu"))
    assert key                                  # served from cache

    after = tts.session_cost("s-shared")
    assert after["vendor_calls"] == before["vendor_calls"] == 0
    assert after["cache_hits"] == before["cache_hits"] == 0    # not metered at all


def test_a_cold_clip_cache_never_stops_the_app_serving(monkeypatch):
    """Warming runs fire-and-forget at boot. A vendor outage at that moment must cost us
    the acknowledgments and nothing else — the interview does not depend on them."""
    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(tts, "read_cache", lambda k: None)

    async def _dead(text, speaker):
        raise RuntimeError("vendor down")

    monkeypatch.setattr(tts, "get_shared_audio_hash", _dead)
    summary = asyncio.run(tts.warm_clip_pack(["ritu"]))
    assert summary["failed"] == len(tts.clip_pack_lines())
    assert summary["warmed"] == 0               # ...and it returned rather than raising


def test_warming_is_a_no_op_once_the_clips_are_on_disk(monkeypatch):
    monkeypatch.setattr(settings, "TTS_ENABLED", True)
    monkeypatch.setattr(tts, "read_cache", lambda k: b"\xff\xfb\x90\x00" + b"\x00" * 900)

    async def _boom(text, speaker):
        raise AssertionError("a warm cache must never call the vendor again")

    monkeypatch.setattr(tts, "get_shared_audio_hash", _boom)
    summary = asyncio.run(tts.warm_clip_pack(["ritu", "shubh"]))
    assert summary["cached"] == len(tts.clip_pack_lines()) * 2
    assert summary["warmed"] == 0 and summary["failed"] == 0
    assert summary["bytes"] > 0


def test_the_clip_pack_is_empty_and_harmless_when_tts_is_off(monkeypatch):
    monkeypatch.setattr(settings, "TTS_ENABLED", False)
    assert asyncio.run(tts.warm_clip_pack(["ritu"])) == {
        "warmed": 0, "cached": 0, "failed": 0, "skipped": 0, "bytes": 0,
    }
    assert asyncio.run(m._try_tts_segments("s1", GREETING, "female", first_only=True)) == []
