"""The clocks: the per-question timer (E7.7) and the device-policy timers (Phase E).

Every one of these guards the same promise — a clock running out must never leave the
candidate stranded. Something always happens next, the interview always moves, and the
session always ends in a scored readout rather than a dead screen.

Runnable with:  python -m pytest tests/test_timers.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app import presence as pr  # noqa: E402
from app import prompts as p  # noqa: E402
from app import stages as s  # noqa: E402
from app.schemas import TurnRequest  # noqa: E402

CFG = {"level": "Fresher", "role": "Backend Engineer", "name": "Asha"}


# ── Expiry with nothing captured -> a SKIP that costs them nothing ──────────

def test_the_skip_marker_is_a_non_answer_by_construction():
    # It reads like an ordinary sentence — long enough and phrased normally — so without
    # this the heuristics would score OUR OWN placeholder as if the candidate had said it.
    assert s.is_non_substantive(s.TIMEOUT_SKIP_TEXT)


def test_a_skip_spends_no_question_slot_in_any_scored_round():
    for stage in ("WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE"):
        assert s.consumes_question_slot(stage, False, timed_out_skip=True) is False
    # A round of 4 still means 4 answers the candidate actually got to give.


def test_a_skip_in_the_reverse_round_does_advance():
    # There is no question of ours to re-ask — the slot is the candidate's own question.
    # If this did not advance, a silent candidate could never reach the close.
    assert s.consumes_question_slot("REVERSE", False, timed_out_skip=True) is True
    new_stage, _ = s.advance_after_reverse(s.stage_total("Fresher", "REVERSE"), "Fresher")
    assert new_stage == "READOUT"


def test_a_skip_is_never_rated():
    # We do not ask anyone to rate their confidence in an answer they never got to give.
    for stage in s.RATING_STAGES:
        assert s.should_await_rating(stage, False) is False


def test_an_ordinary_answer_is_untouched_by_the_skip_path():
    # The default keeps the FIX 2 behaviour exactly: substantive answers spend a slot,
    # non-answers in a rating-gated round do not.
    assert s.consumes_question_slot("DOMAIN", True) is True
    assert s.consumes_question_slot("DOMAIN", False) is False
    assert s.consumes_question_slot("WARMUP", False) is True


# ── Expiry with something captured -> the partial IS the answer ─────────────

def test_a_partial_answer_is_scored_like_any_other_answer():
    partial = "We'd cap the exposure per borrower and re-price the tranche, because the"
    assert not s.is_non_substantive(partial)          # cut off, but real content
    assert s.consumes_question_slot("DOMAIN", True) is True
    assert s.should_await_rating("DOMAIN", True) is True


# ── The request contract: only a skip may arrive empty ─────────────────────

def test_only_a_skip_may_post_an_empty_message():
    ok = TurnRequest(session_id="s", timeout="skip")
    assert ok.message == ""
    with pytest.raises(ValidationError):
        TurnRequest(session_id="s")                      # an ordinary empty turn
    with pytest.raises(ValidationError):
        TurnRequest(session_id="s", message="   ", timeout="partial")


def test_the_client_cannot_invent_a_timeout_kind():
    with pytest.raises(ValidationError):
        TurnRequest(session_id="s", message="hi", timeout="ran_out")


# ── The interviewer moves the interview ON — it never re-asks a lost question ──

STEP_DOWN = "step the difficulty DOWN"


def test_a_skip_moves_on_instead_of_stepping_down_to_the_same_topic():
    # A non-answer means "I don't know" -> the interviewer simplifies and re-asks.
    # A TIMEOUT means the clock beat them -> re-asking it more simply would punish them
    # for our clock. These two must not be confused.
    non_answer = p.stage_turn_directive(CFG, "DOMAIN", 1, substantive=False)
    assert STEP_DOWN in non_answer

    skipped = p.stage_turn_directive(CFG, "DOMAIN", 1, substantive=False, timeout="skip")
    assert STEP_DOWN not in skipped
    assert "did not answer that question" in skipped
    # ...and it still carries the ordinary "ask the next planned question" plan.
    assert "DOMAIN ROUND (question 2 of 4)" in skipped


def test_the_partial_directive_engages_with_what_they_did_get_out():
    d = p.stage_turn_directive(CFG, "CASE", 1, substantive=True, timeout="partial")
    assert "INCOMPLETE" in d
    assert "let's move on" in d
    low = d.lower()
    assert "do not ask them to finish it" in low
    # Never scold someone for a clock they did not control.
    assert "do not hold it against them" in low


def test_a_timeout_note_never_replaces_the_presence_ladder():
    note = pr.escalation_directive(2)
    d = p.stage_turn_directive(CFG, "DOMAIN", 1, presence_note=note, timeout="skip")
    assert d.startswith(note.strip())          # attention is still raised first
    assert "did not answer that question" in d


def test_no_timeout_means_no_note_at_all():
    assert p.timeout_directive("") == ""
    assert p.timeout_directive(None) == ""
    plain = p.stage_turn_directive(CFG, "DOMAIN", 1)
    assert "TIME NOTE" not in plain


# ── Device policy: the camera grace is a second chance, not a countdown ─────

def test_camera_grace_is_60s_and_only_fires_if_it_is_still_off():
    assert pr.CAMERA_GRACE_SECONDS == 60
    assert pr.camera_grace_expired(59) is False    # inside the grace: nothing escalates
    assert pr.camera_grace_expired(60) is True
    assert pr.camera_grace_expired(None) is False  # never explode on bad input
    assert pr.camera_grace_expired("junk") is False


def test_a_lapsed_grace_walks_the_existing_ladder_to_the_wrap():
    # Each lapsed grace re-reports camera_off, so the ladder we already had does the work.
    assert pr.camera_ladder_action(1, True) == "nudge"   # off -> asked to turn it back on
    assert pr.camera_ladder_action(2, True) == "warn"    # still off after the grace
    assert pr.camera_ladder_action(3, True) == "wrap"    # still off after the warning
    # And a camera-off JOIN never enters the ladder at all — accessibility, not a breach.
    assert pr.camera_ladder_action(3, False) == "none"


# ── Device policy: 90s of two dead channels is abandonment ─────────────────

def test_abandonment_needs_both_channels_dead_for_90s():
    assert pr.SILENT_ABANDON_SECONDS == 90
    assert pr.is_abandonment(90, mic_live=False, typed_chars=0) is True
    assert pr.is_abandonment(89, mic_live=False, typed_chars=0) is False


def test_typing_keeps_the_interview_alive():
    # Typed answers are first-class: a muted candidate who is typing is NOT abandoning.
    assert pr.is_abandonment(300, mic_live=False, typed_chars=1) is False


def test_a_live_mic_is_never_abandonment():
    # They may just be thinking. Thinking too long is the per-question clock's business,
    # and it ends in a skip and the next question — never in ending their session.
    assert pr.is_abandonment(300, mic_live=True, typed_chars=0) is False


def test_abandonment_never_explodes_on_bad_input():
    assert pr.is_abandonment(None, mic_live=False) is False
    assert pr.is_abandonment("junk", mic_live=False) is False


# ── Session expiry -> a wrap, and a wrap is still a scored readout ─────────

def test_session_expiry_wraps_to_the_readout_and_scores_what_happened():
    new_stage, at = s.early_wrap_transition("BEHAVIOURAL")
    assert new_stage == "READOUT"
    assert at == "BEHAVIOURAL"
    assert s.next_action("READOUT", False) == "readout"   # -> the debrief runs
    # The wrap moves the stage and nothing else. No score is zeroed as a punishment.
    assert s.band_for(72) == "Interview-Ready"


def test_the_three_wrap_reasons_are_named_once_and_shared():
    assert pr.WRAP_CAMERA_OFF == "camera_off"
    assert pr.WRAP_NO_ANSWER == "no_answer_timeout"
    assert pr.WRAP_SESSION_TIME_UP == "session_time_up"
    for r in (pr.WRAP_CAMERA_OFF, pr.WRAP_NO_ANSWER, pr.WRAP_SESSION_TIME_UP):
        assert len(r) <= 40      # WrapRequest.reason is capped at 40 chars
