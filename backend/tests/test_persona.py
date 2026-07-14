"""PART 1 (the interviewer's soul) + E2 (voice & pacing).

Pins the things that make the interviewer feel like a person rather than an assistant,
and the things that must never leak into what a candidate hears or reads.

Runnable with:  python -m pytest tests/test_persona.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import presence as pr  # noqa: E402
from app import prompts as p  # noqa: E402
from app import tts  # noqa: E402


def flat(text):
    """Collapse whitespace — the prompt is hard-wrapped, so assertions must not care
    where a line happens to break."""
    return " ".join((text or "").split())


def _cfg(**over):
    base = {"name": "Asha", "role": "Backend Engineer", "level": "Fresher",
            "company": "Razorpay", "duration_min": 20, "difficulty": "Realistic",
            "mode": "interview", "round": "full", "focus": [], "intro": "",
            "interviewer_name": "Priya"}
    base.update(over)
    return base


# ── The persona IS a person, not an assistant ──────────────────────────────

def test_persona_is_the_named_interviewer_not_an_assistant():
    s = p.build_persona(_cfg())
    assert "YOU ARE PRIYA" in flat(s)
    assert "NOT an assistant, a coach, or an AI helper" in flat(s)
    assert "Backend Engineer" in flat(s)


def test_persona_caps_turn_length_and_bans_generic_acknowledgement():
    s = p.build_persona(_cfg())
    assert "2-3 SHORT sentences per turn" in flat(s)
    assert "One question at a time" in flat(s)
    assert "FORBIDDEN" in flat(s) and "Great answer, next question" in flat(s)
    # Never a compound question; never answer for them.
    assert "multi-part compound question" in flat(s)


def test_persona_never_comments_on_hinglish_or_things_they_cannot_fix():
    s = p.build_persona(_cfg())
    assert "NEVER comment on their language choice" in flat(s)
    assert "accent" in flat(s) and "cannot fix in this room" in flat(s)


# ── tone_hint is derived from difficulty (register, not persona) ────────────

def test_tone_hint_mapping():
    assert p.tone_hint("Easy") == "warm"
    assert p.tone_hint("Realistic") == "neutral"
    assert p.tone_hint("Stretch") == "probing"
    assert p.tone_hint("") == "neutral"          # safe default


def test_difficulty_changes_the_register_not_the_rigor():
    easy = p.build_persona(_cfg(difficulty="Easy"))
    stretch = p.build_persona(_cfg(difficulty="Stretch"))
    assert "WARM" in flat(easy) and "ONE clarifying follow-up at most" in flat(easy)
    assert "PROBING" in flat(stretch) and "curveball constraint" in flat(stretch)
    # Pressure comes from precision, never from tone.
    assert "pressure through precision" in flat(stretch)


# ── Behaviour only. No emotion attribution, ever. ─────────────────────────

def test_persona_forbids_emotion_attribution_explicitly():
    s = p.build_persona(_cfg())
    assert "DESCRIBE BEHAVIOUR ONLY" in flat(s)
    assert "never attribute an emotion" in flat(s).lower()
    # The specific attributions the spec calls out are named as prohibitions.
    for w in ("nervous", "bored", "disinterested", "anxious", "unconfident"):
        assert w in s.lower()
    assert 'you seem/seemed/look/felt' in flat(s).lower()


def test_the_word_cheating_appears_nowhere_at_all():
    """Not in the persona, not in any directive, not even to forbid it — naming it in
    the prompt primes the model to echo it. (An earlier draft did exactly that.)"""
    blobs = [
        p.build_persona(_cfg()),
        p.build_system_prompt(_cfg()),
        p.build_kickoff(_cfg(), seed=1),
        p.stage_turn_directive(_cfg(), "DOMAIN", 1),
        pr.escalation_directive(1), pr.escalation_directive(2), pr.escalation_directive(3),
        pr.camera_directive("nudge"), pr.camera_directive("warn"), pr.wrap_directive(),
    ]
    for b in blobs:
        assert "cheat" not in b.lower()


# ── Round context + reacting to what they ACTUALLY said ───────────────────

def test_round_goal_and_prior_answer_ride_the_turn_directive():
    d = p.stage_turn_directive(
        _cfg(), "DOMAIN", 1,
        prior_answer_summary="We moved the ledger to Postgres. It took three weeks.",
    )
    assert "CURRENT ROUND: Domain" in flat(d)
    assert p.round_goal("DOMAIN") in flat(d)
    assert "three weeks" in d                      # they must be able to pick up a detail
    assert "generic acknowledgement is forbidden" in flat(d)


def test_turn_directive_without_a_prior_answer_still_works():
    d = p.stage_turn_directive(_cfg(), "WARMUP", 0)
    assert "CURRENT ROUND: Warm-up" in flat(d)
    assert "THEIR LAST ANSWER" not in d


def test_presence_note_still_precedes_the_round_context():
    note = pr.escalation_directive(2)
    d = p.stage_turn_directive(_cfg(), "DOMAIN", 1, presence_note=note,
                               prior_answer_summary="I used Redis.")
    assert d.startswith(note.strip())


# ── E2: voice & pacing ────────────────────────────────────────────────────

def test_sentences_split_for_per_clip_synthesis():
    out = tts.split_sentences("Good, that lands. Three weeks is a while. What made it take that long?")
    assert out == ["Good, that lands.", "Three weeks is a while.", "What made it take that long?"]
    assert tts.split_sentences("") == []
    # Markdown never reaches the voice.
    assert "**" not in " ".join(tts.split_sentences("**Bold** point. Next?"))


def test_pacing_constants_match_the_spec():
    from app import main as m
    assert 300 <= m.INTER_SENTENCE_PAUSE_MS <= 450     # a human beat between sentences
    assert m.PRE_QUESTION_PAUSE_MS == 700              # let the question land


# ── MIC = MEET SEMANTICS: the spoken "you're on mute" fork ────────────────

def test_mute_fork_lines_offer_both_paths_and_vary():
    lines = [p.mute_fork_line(i) for i in range(4)]
    assert len(set(lines)) > 1                       # never canned
    for line in lines:
        low = line.lower()
        assert "mute" in low                          # name the actual problem
        assert "typ" in low                           # ...and always offer the other path


def test_mute_fork_directive_never_belittles_typing_and_never_re_asks():
    d = p.MUTE_FORK_DIRECTIVE
    assert "unmute" in d.lower()
    # Typed answers are first-class. The fork must not imply otherwise.
    assert "lesser option" in d
    assert "first-class" in d
    # It offers a fork; it does not repeat the question or hurry them.
    assert "do not repeat your question" in d.lower()
    assert "impatient" in d


def test_the_persona_itself_carries_the_mute_fork():
    # The interviewer knows this moment natively — it is not bolted on.
    s = flat(p.build_persona(_cfg()))
    assert "You're on mute" in s
    assert "Typed answers are FULLY first-class" in s


def test_mute_fork_never_asks_a_question_so_it_cannot_cost_a_slot():
    """The fork rides /session/reask, which inserts no message and changes no state.
    The directive must therefore not smuggle a new question into the turn."""
    d = p.MUTE_FORK_DIRECTIVE.lower()
    assert "one sentence" in d
    assert "do not repeat your question" in d
