"""CRITICAL — the pressure panel.

A fourth difficulty: a stress-interview simulator, for candidates who want to be challenged
hard. It is a real genre in Indian hiring (bank PO panels, consulting partners, some PSU
boards) and candidates ask for it.

It is also the single most dangerous thing in this codebase, because "be harsh with them"
is one bad prompt away from cruelty, and the person on the other end is a job-seeker who
already feels precarious. So the load-bearing half of this file is not the tests that prove
the mode is tough. It is the tests that prove the guardrails DID NOT MOVE:

    the criticism lands on the ANSWER and the REASONING. Never on the person.

Every prohibition that binds Easy binds Critical. The mode raises the STANDARD, not the
temperature. If a future change makes one of these fail, the mode is wrong, not the test.

Runnable with:  python -m pytest tests/test_critical.py
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
from app.schemas import StartSessionRequest  # noqa: E402


def flat(text):
    return " ".join((text or "").split())


def _cfg(**over):
    base = {"name": "Asha", "role": "Credit Risk Analyst", "level": "3-10 years",
            "company": "ICICI", "duration_min": 30, "difficulty": "Critical",
            "mode": "interview", "round": "full", "focus": [], "intro": "",
            "interviewer_name": "Riya"}
    base.update(over)
    return base


ALL_MODES = ("Easy", "Realistic", "Stretch", "Critical")


# ── The mode exists, and you cannot reach it by accident ─────────────────────

def test_critical_is_a_real_difficulty_the_api_accepts():
    req = StartSessionRequest(role="Credit Risk Analyst", level="Fresher",
                              difficulty="Critical")
    assert req.difficulty == "Critical"


def test_the_other_three_difficulties_still_work_exactly_as_before():
    for d in ("Easy", "Realistic", "Stretch"):
        assert StartSessionRequest(role="X", level="Fresher", difficulty=d).difficulty == d


# ── What the mode actually does ──────────────────────────────────────────────

def test_the_persona_challenges_every_substantive_answer_at_least_once():
    s = flat(p.build_persona(_cfg()))
    assert "CHALLENGE EVERY SUBSTANTIVE ANSWER at least once" in s
    assert "Make them defend it" in s


def test_the_persona_is_openly_sceptical_of_weak_reasoning():
    s = flat(p.build_persona(_cfg()))
    assert "BE OPENLY SCEPTICAL of weak reasoning" in s
    # The spec's own example line, because it is exactly the right register: it goes after
    # the NUMBER, not the person who quoted it.
    assert "That number doesn't hold up" in s
    assert "name the hole" in s


def test_the_persona_interrupts_rambling_with_a_redirect():
    s = flat(p.build_persona(_cfg()))
    assert "INTERRUPT RAMBLING" in s
    assert "90 seconds" in s
    assert "redirect" in s.lower()


def test_the_persona_is_blunt_in_its_reactions():
    s = flat(p.build_persona(_cfg()))
    assert "BE BLUNT IN YOUR REACTIONS" in s
    assert "That's not an answer to what I asked" in s
    assert "No cushioning" in s


def test_critical_gets_two_curveballs_not_one():
    crit = flat(p.build_system_prompt(_cfg()))
    assert "Insert TWO unexpected pressure questions" in crit
    # Stretch keeps its single curveball; the others keep none.
    assert "ONE unexpected pressure question" in flat(p.build_system_prompt(_cfg(difficulty="Stretch")))
    assert "Do not use curveball questions" in flat(p.build_system_prompt(_cfg(difficulty="Realistic")))


def test_critical_carries_its_own_tone_and_the_face_follows_it():
    assert p.tone_hint("Critical") == "critical"
    # The pressure panel never softens — not in the warm-up, not in the greeting. A smiling
    # opener would be a bait-and-switch on someone who asked to be put under pressure.
    assert p.turn_tone("Critical", "WARMUP") == "critical"
    assert p.turn_tone("Critical", "DOMAIN") == "critical"
    # Every other mode still opens warm, exactly as it did.
    assert p.turn_tone("Realistic", "WARMUP") == "warm"
    assert p.turn_tone("Easy", "WARMUP") == "warm"
    assert p.turn_tone("Stretch", "WARMUP") == "warm"


# ══ THE GUARDRAILS. THESE ARE THE TESTS THAT MATTER. ════════════════════════

def test_the_criticism_targets_the_answer_and_the_reasoning_never_the_person():
    s = flat(p.build_persona(_cfg()))
    assert "lands on the ANSWER and the REASONING. NEVER on the person" in s
    # Stated as a worked example, because the abstract rule is easy to nod along to and
    # then violate. This is the line, drawn where a model can see it.
    assert "That reasoning is circular" in s
    assert "You are not very bright" in s and "never will be" in s


def test_the_banned_vocabulary_is_banned_in_critical_too():
    """No insults, no mockery, no sarcasm, no contempt. The Tone block is NON-NEGOTIABLE in
    all four difficulties, and the addendum says so again in its own words."""
    persona = flat(p.build_persona(_cfg()))
    system = flat(p.build_system_prompt(_cfg()))

    assert "No insults. No mockery. No sarcasm. No contempt." in persona
    # The persona's standing prohibitions are still there, unweakened.
    assert "Never mock, never sigh in text, never use sarcasm" in persona
    # ...and so is the system prompt's, which is where the hardest line lives.
    assert "NEVER use foul, abusive, mocking, sarcastic, or belittling language" in system
    assert "NON-NEGOTIABLE" in system


def test_the_attribution_ban_holds_in_critical_most_of_all():
    """DESCRIBE BEHAVIOUR ONLY. You may never tell a candidate they SEEM rattled — you
    cannot see inside anyone, and under pressure is exactly when a model would try."""
    s = p.build_persona(_cfg())
    flatted = flat(s)
    assert "DESCRIBE BEHAVIOUR ONLY — THIS IS ABSOLUTE" in flatted
    assert "never attribute an emotion" in flatted.lower()
    assert "No emotion attribution" in flatted
    assert "binds you here EXACTLY as it does everywhere else" in flatted
    assert "rattled" in flatted and "out of their depth" in flatted
    for word in ("nervous", "bored", "disinterested", "anxious", "unconfident"):
        assert word in s.lower()


def test_never_a_word_about_their_background_english_accent_or_college():
    """Those are not answers and they are not reasoning. They are the person — and for an
    Indian hiring product this is the failure mode that would actually hurt somebody."""
    s = flat(p.build_persona(_cfg()))
    assert "Never a word about their background, their English, their accent, or their college" in s
    # The standing rule is still there underneath it.
    assert "Never comment on their accent" in s
    assert "NEVER comment on their language choice" in s


def test_pressure_is_a_standard_not_a_temperature():
    s = flat(p.build_persona(_cfg()))
    assert "Pressure is a STANDARD you hold them to, not a temperature you raise" in s
    assert "toughest fair interviewer they will ever meet — not an unkind one" in s
    # And the register block says the same thing where the model reads the register.
    assert "pressure comes from the STANDARD you hold, not from your manners" in s


def test_shame_is_forbidden_in_every_mode_including_this_one():
    """The one Tone line that MOVES with difficulty is the gentleness of the probe. What
    does not move is the protection of the person being probed: shame lands on them, and it
    is out in all four modes."""
    for mode in ALL_MODES:
        assert "Never shame a wrong answer" in flat(p.build_system_prompt(_cfg(difficulty=mode))), mode
    # Critical drops "probe gently" — and replaces it with where the criticism must land.
    crit = flat(p.build_system_prompt(_cfg()))
    assert "go after the REASONING — never the person who offered it" in crit
    assert "probe gently" not in crit
    # ...which every other mode keeps.
    assert "Acknowledge the attempt, probe gently" in flat(p.build_system_prompt(_cfg(difficulty="Easy")))


def test_a_frustrated_or_rude_candidate_is_still_met_calmly_under_pressure():
    """The pressure panel does not get to escalate with someone who snaps at it. This is
    the guardrail most likely to be quietly lost, because the mode's whole premise argues
    against it."""
    s = flat(p.build_system_prompt(_cfg()))
    assert "If candidate is frustrated, rude, or uses profanity: respond calmly" in s
    assert "regardless of what the candidate does" in s


def test_the_word_cheating_still_appears_nowhere_in_critical():
    blobs = [
        p.build_persona(_cfg()),
        p.build_system_prompt(_cfg()),
        p.build_kickoff(_cfg(), seed=1),
        p.stage_turn_directive(_cfg(), "DOMAIN", 1),
        p.debrief_instruction(_cfg()),
        p.CRITICAL_ADDENDUM,
        p.CRITICAL_DEBRIEF_ADDENDUM,
    ]
    for b in blobs:
        assert "cheat" not in b.lower()


# ── The addendum applies to CRITICAL ONLY ────────────────────────────────────

def test_the_addendum_is_absent_from_every_other_mode():
    """'Persona addendum for this mode ONLY.' A stray pressure-panel instruction leaking
    into an Easy session — a fresher's first ever mock interview — is the worst bug this
    sprint could ship."""
    for mode in ("Easy", "Realistic", "Stretch"):
        s = p.build_persona(_cfg(difficulty=mode))
        assert p.CRITICAL_ADDENDUM not in s, mode
        assert "THE PRESSURE PANEL" not in s, mode
        assert "BE BLUNT IN YOUR REACTIONS" not in s, mode
        assert "INTERRUPT RAMBLING" not in s, mode


def test_easy_mode_is_byte_for_byte_what_it_was():
    """The gentlest mode is the one a nervous fresher meets. Nothing in this sprint may
    have touched it."""
    s = flat(p.build_persona(_cfg(difficulty="Easy")))
    assert "WARM — encouraging" in s
    assert "ONE clarifying follow-up at most per question" in s
    assert "Rephrase generously if they stumble" in s
    assert "sceptical" not in s.lower()
    assert "blunt" not in s.lower()


# ── The readout: the mentor voice survives the pressure panel ────────────────

def test_the_readout_names_the_mode_the_candidate_chose():
    d = flat(p.debrief_instruction(_cfg()))
    assert "THIS WAS THE PRESSURE PANEL — SAY SO." in d
    # The spec's own line. Without it a hard-won 40 reads as a plain 40, and the candidate
    # has no idea the bar they were scored against was one they raised on themselves.
    assert "You chose the pressure panel — here is what held up under it and what cracked." in d


def test_the_readout_keeps_its_mentor_voice_and_scores_honestly():
    d = flat(p.debrief_instruction(_cfg()))
    assert "SAME MENTOR VOICE as every other readout" in d
    assert "The interviewer was blunt; the mentor is not" in d
    # It must not go soft as an apology for how hard the mode was...
    assert "Do not inflate anything as a consolation" in d
    # ...nor turn the debrief into a second beating.
    assert "Nothing in the debrief mocks, sneers, or scores the person rather than the work" in d
    # The base readout's own rules still bind it.
    assert "Never harsh, never mocking" in d
    assert "WHAT WENT WELL" in d


def test_holding_up_under_pressure_is_named_as_a_strength_to_look_for():
    d = flat(p.debrief_instruction(_cfg()))
    assert "Where they HELD under a challenge, say so specifically and quote it" in d


def test_every_other_mode_gets_the_readout_completely_unchanged():
    for mode in ("Easy", "Realistic", "Stretch"):
        d = p.debrief_instruction(_cfg(difficulty=mode))
        assert d == p.DEBRIEF_INSTRUCTION, mode
        assert "pressure panel" not in d.lower(), mode
    # And a missing cfg (any older caller) must not explode.
    assert p.debrief_instruction(None) == p.DEBRIEF_INSTRUCTION
    assert p.debrief_instruction({}) == p.DEBRIEF_INSTRUCTION
