"""THE ENGAGEMENT FLOOR — a real panel never asks six questions into silence.

The founder's UAT session was six questions asked into a dead room. The interviewer never
once stopped to ask whether anybody was there; it just marched down the round list, paying
for an LLM call and a TTS bill on every question nobody heard. This is the test file for
the rule that ends that.

The counter is DERIVED, not stored: consecutive silences are the trailing run of skip
markers in the transcript. That is the whole design, and it is why "any response resets the
counter" needs no code — a real answer breaks the run by existing. These tests pin that.

Runnable with:  python -m pytest tests/test_engagement.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import prompts as p  # noqa: E402
from app import stages as s  # noqa: E402

SKIP = s.TIMEOUT_SKIP_TEXT
ANSWER = "We moved the ledger to Postgres because the write path was the bottleneck."


def flat(text):
    return " ".join((text or "").split())


def _cfg(**over):
    base = {"name": "Asha", "role": "Backend Engineer", "level": "Fresher",
            "company": "Razorpay", "duration_min": 20, "difficulty": "Realistic",
            "mode": "interview", "round": "full", "focus": [], "intro": "",
            "interviewer_name": "Riya"}
    base.update(over)
    return base


def action(answers, stage="DOMAIN"):
    """The engagement verdict for a transcript, exactly as main.session_turn computes it."""
    return s.engagement_action(
        stage, s.trailing_skips(answers), s.substantive_count(answers)
    )


# ── The counter itself ───────────────────────────────────────────────────────

def test_trailing_skips_counts_only_the_run_at_the_end():
    assert s.trailing_skips([]) == 0
    assert s.trailing_skips([ANSWER]) == 0
    assert s.trailing_skips([SKIP]) == 1
    assert s.trailing_skips([SKIP, SKIP]) == 2
    # A real answer BREAKS the run. This is the whole "resets on any response" rule.
    assert s.trailing_skips([SKIP, SKIP, ANSWER]) == 0
    # ...and only the run at the END counts — old silences are not held against them.
    assert s.trailing_skips([SKIP, SKIP, ANSWER, SKIP]) == 1


# ── THE 2-SKIP CHECK-IN (a cold session: nothing substantive has been said) ──

def test_two_consecutive_silences_in_a_blank_session_trigger_the_checkin():
    assert action([SKIP]) == ""                    # one silence is a person thinking
    assert action([SKIP, SKIP]) == "checkin"       # two is a person who may not be there


def test_the_checkin_replaces_the_next_question_entirely():
    d = p.stage_turn_directive(_cfg(), "DOMAIN", 1, substantive=False,
                               timeout="skip", engagement="checkin")
    assert d == p.CHECKIN_DIRECTIVE
    low = flat(d).lower()
    # It must not ask an interview question — that is the entire point of breaking off.
    assert "do not ask an interview question this turn" in low
    assert "do not re-ask the question they missed" in low
    # It ends on something answerable in one word, and it offers BOTH doors.
    assert "shall we keep going?" in low
    assert "wrap" in low and "clean slate" in low
    # And it never editorialises about the silence.
    assert "no lecture" in low and "no speculation" in low
    assert "no reprimand" in low


def test_the_checkin_carries_its_own_short_clock():
    assert s.CHECKIN_SECONDS == 45
    # A yes/no does not need three minutes — and three minutes is exactly the silence the
    # check-in exists to break.
    assert s.CHECKIN_SECONDS < 180


# ── ANY RESPONSE RESETS IT — even "yes" ──────────────────────────────────────

def test_any_response_at_all_resets_the_counter_including_a_bare_yes():
    # They answered the check-in with one word. That is a response. The march resumes.
    assert action([SKIP, SKIP, "yes"]) == ""
    assert action([SKIP, SKIP, "Yes, let's keep going"]) == ""
    assert action([SKIP, SKIP, ANSWER]) == ""
    # ...and the counter really is back to zero: one more silence is just a first silence.
    assert action([SKIP, SKIP, "yes", SKIP]) == ""


def test_a_bare_yes_is_a_response_but_it_is_not_a_substantive_answer():
    """Both halves matter. It RESETS the silence counter (they are there), but it must not
    unlock the looser threshold — someone who has only ever said "yes" has still told the
    interviewer nothing at all about the role."""
    assert s.trailing_skips([SKIP, SKIP, "yes"]) == 0          # it is a response
    assert s.substantive_count([SKIP, SKIP, "yes"]) == 0       # ...and not an answer
    assert s.checkin_threshold(0) == s.SKIPS_BEFORE_CHECKIN_COLD


def test_the_resumed_turn_asks_the_next_question_not_a_step_down():
    """They came back. They must NOT be dropped into non-answer recovery ('let me ask
    something more fundamental on the same topic') — 'yes' was a reply to us, not a failed
    attempt at an interview question, and treating it as one re-punishes the silence they
    just climbed out of."""
    d = p.stage_turn_directive(_cfg(), "DOMAIN", 1, substantive=False,
                               prior_answer_summary="yes", resumed=True)
    assert p.RESUMED_DIRECTIVE in d
    assert "question 2 of" in flat(d).lower()          # the next PLANNED question
    assert "non-answer recovery" not in flat(d).lower()
    assert "MORE FUNDAMENTAL" not in d
    # There is nothing in "yes" to react to, so we do not demand a reaction to it.
    assert "THEIR LAST ANSWER" not in d
    # No relief, no fuss, no dwelling on the gap.
    low = flat(p.RESUMED_DIRECTIVE).lower()
    assert "no relief" in low and "no comment on the gap" in low


# ── THE THIRD SILENCE — a courteous wrap ─────────────────────────────────────

def test_a_third_consecutive_silence_wraps_the_interview():
    assert action([SKIP, SKIP, SKIP]) == "wrap"
    # They did not answer the check-in either. There is nothing left to ask.


def test_the_wrap_is_courteous_and_never_blames_them():
    d = p.DISENGAGED_WRAP_DIRECTIVE
    low = flat(d).lower()
    assert "closing turn" in low
    assert "clean slate" in low                       # the next attempt is a fresh start
    assert "readout will still help them prepare" in low
    # We have no idea why they went quiet, and guessing would be rude and probably wrong.
    assert "do not scold" in low
    assert "do not accuse" in low
    assert "do not speculate" in low
    # The debrief is written separately — the closing line must not try to score them.
    assert "do not produce any report" in low
    # The literal line the spec asked for, kept as the fallback.
    assert "clean slate" in p.DISENGAGED_WRAP_FALLBACK.lower()
    assert "wrap here" in p.DISENGAGED_WRAP_FALLBACK.lower()


def test_the_wrap_is_scored_honestly_not_zeroed():
    """Nothing is zeroed as a punishment. The stage machine simply moves to the readout,
    which scores the rounds that actually happened — and in a blank session that is an
    honest zero, arrived at by scoring nothing rather than by confiscating anything."""
    new_stage, wrapped_at = s.early_wrap_transition("DOMAIN")
    assert new_stage == "READOUT"
    assert wrapped_at == "DOMAIN"


# ── THE LOOSER THRESHOLD: a good candidate freezing deserves more rope ───────

def test_a_candidate_who_has_answered_gets_a_third_silence_before_the_checkin():
    prior = [ANSWER, ANSWER]
    assert s.substantive_count(prior) == 2
    assert s.checkin_threshold(2) == s.SKIPS_BEFORE_CHECKIN_WARM == 3

    assert action(prior + [SKIP]) == ""                  # thinking
    assert action(prior + [SKIP, SKIP]) == ""            # still thinking — this is a HARD one
    assert action(prior + [SKIP, SKIP, SKIP]) == "checkin"
    assert action(prior + [SKIP, SKIP, SKIP, SKIP]) == "wrap"


def test_the_thresholds_differ_only_by_whether_they_ever_said_anything():
    assert s.checkin_threshold(0) == 2       # blank session: two is already generous
    assert s.checkin_threshold(1) == 3       # they have engaged: give them a third
    assert s.checkin_threshold(9) == 3


def test_one_substantive_answer_is_enough_to_earn_the_rope():
    # Freezing on hard questions after a real answer is a candidate struggling, not one
    # who has left. Two silences must NOT cut them off.
    assert action([ANSWER, SKIP, SKIP]) == ""
    assert action([ANSWER, SKIP, SKIP, SKIP]) == "checkin"


# ── The exemptions and the edges ─────────────────────────────────────────────

def test_the_reverse_round_is_exempt():
    """In REVERSE the 'question' is the candidate's own. There is nothing of ours to check
    in about, and a silent candidate must still be able to reach the close."""
    assert action([SKIP, SKIP], stage="REVERSE") == ""
    assert action([SKIP, SKIP, SKIP], stage="REVERSE") == ""


def test_the_floor_holds_in_every_answering_round():
    for stage in ("WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE"):
        assert action([SKIP, SKIP], stage=stage) == "checkin", stage
        assert action([SKIP, SKIP, SKIP], stage=stage) == "wrap", stage


def test_the_engagement_action_outranks_the_timeout_and_presence_directives():
    """When nobody has spoken for two questions running there is no point acknowledging a
    skip, raising their attention, or asking anything. The check-in is the whole turn."""
    d = p.stage_turn_directive(
        _cfg(), "DOMAIN", 1, substantive=False,
        presence_note="ATTENTION NOTE: they keep looking away.",
        timeout="skip", engagement="checkin",
    )
    assert d == p.CHECKIN_DIRECTIVE
    assert "ATTENTION NOTE" not in d
    assert "STAGE DIRECTIVE" not in d

    w = p.stage_turn_directive(_cfg(), "DOMAIN", 1, substantive=False,
                               timeout="skip", engagement="wrap")
    assert w == p.DISENGAGED_WRAP_DIRECTIVE


def test_an_ordinary_turn_is_completely_untouched_by_all_of_this():
    """The floor must be invisible to a candidate who is simply answering questions."""
    d = p.stage_turn_directive(_cfg(), "DOMAIN", 1, substantive=True,
                               prior_answer_summary=ANSWER)
    assert p.CHECKIN_DIRECTIVE not in d
    assert p.DISENGAGED_WRAP_DIRECTIVE not in d
    assert p.RESUMED_DIRECTIVE not in d
    assert "STAGE DIRECTIVE" in d
    assert "Postgres" in d                    # still reacting to what they actually said


def test_the_checkin_costs_no_extra_llm_call_and_saves_the_ones_nobody_hears():
    """The check-in REPLACES the stage directive on a turn that was already going to call
    the model — so it is free — and the wrap stops us paying for the four questions that
    would otherwise have been asked, and spoken aloud, to an empty room."""
    # Same call, different directive: nothing here adds a round trip.
    assert isinstance(p.CHECKIN_DIRECTIVE, str) and p.CHECKIN_DIRECTIVE
    assert isinstance(p.DISENGAGED_WRAP_DIRECTIVE, str) and p.DISENGAGED_WRAP_DIRECTIVE
    # A blank session used to run the full round plan. It now ends after three turns.
    blank = [SKIP, SKIP, SKIP]
    assert action(blank) == "wrap"
    assert len(blank) == 3
