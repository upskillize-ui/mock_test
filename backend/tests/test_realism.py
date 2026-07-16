"""Conversation Realism v2 — dynamic interviewer identity (prompts.py).

Guards the things that make openings genuinely dynamic rather than templated:
the kickoff must demand improvisation (never copy the flavor examples, never repeat
an opening), must constrain the opening without templating it, and the improvised
identity must be replayed into every later turn so the interviewer stays in character.

Runnable with:  python -m pytest tests/test_realism.py
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


def _cfg(**over):
    base = {"name": "Asha", "role": "Data Analyst", "level": "Fresher", "company": "TCS",
            "duration_min": 20, "difficulty": "Realistic", "mode": "interview",
            "round": "full", "focus": [], "intro": ""}
    base.update(over)
    return base


# ── The kickoff must force improvisation, not a template ────────────────────

def test_kickoff_demands_improvisation_and_forbids_copying_examples():
    k = build = p.build_kickoff(_cfg())
    assert "INVENT YOUR INTERVIEWER IDENTITY" in k
    # Flavor examples must be explicitly marked as never-copy.
    assert "FLAVOR ONLY" in k and "never copy" in k.lower()
    # Repeating an opening across sessions is called out as a failure.
    assert "FAILURE" in k
    assert "fresh phrasing every single session" in build.lower()


def test_kickoff_opening_constraints_not_a_template():
    """The opening is a RITUAL now — greet, ice-breaker, intent question — not a formula.

    THIS TEST'S CONTRACT CHANGED (Persona/Warmth item 3). It used to assert the opening was
    2-3 sentences and ENDED on a role-shaped question, explicitly forbidding rapport. The
    warm-openings spec inverts exactly that: the opening now ends on the INTENT question
    ("what do you want out of today?"), and the first role question comes on the next turn,
    once they have answered it. The 20-40 second budget buys the third beat, so the cap
    moved 2-3 -> 3-4 sentences; "not a paragraph at someone who has just sat down" is still
    the constraint, and it is still asserted below.
    """
    k = p.build_kickoff(_cfg())
    assert "3 or 4 SHORT sentences" in k
    assert "Not a paragraph" in k
    assert "20-40 seconds" in k
    # The three beats, in order.
    greet = k.index("BEAT 1 — GREET THEM")
    breaker = k.index("BEAT 2 — ONE SAFE ICE-BREAKER")
    intent = k.index("BEAT 3 — THE INTENT QUESTION")
    assert greet < breaker < intent
    # It ends on the intent question, NOT on a role question.
    assert "Your opening does NOT end on a role question" in k
    # Identity is tone-only — never difficulty/structure.
    assert "never changes difficulty" in k.lower() or "TONE ONLY" in k


def test_the_opening_streams_before_the_identity_does():
    """FAST START: `opening` MUST be the first key in the kickoff JSON. It is what the
    candidate actually hears, and putting it first is what lets us start synthesising the
    interviewer's first sentence while she is still writing her third."""
    k = p.build_kickoff(_cfg())
    assert k.index('"opening"') < k.index('"identity"')
    assert 'Write "opening" first' in k


def test_reassurance_only_for_freshers():
    fresher = p.build_kickoff(_cfg(level="Fresher"))
    senior = p.build_kickoff(_cfg(level="10-20 years"))
    assert "AT MOST ONE short reassurance line" in fresher
    assert "NO reassurance" in senior


def test_kickoff_asks_for_identity_json():
    k = p.build_kickoff(_cfg())
    assert '"identity"' in k and '"opening"' in k


# ── Anti-convergence: the model collapses onto one persona without help ──────
# Measured against the live model: with identical inputs it produced the SAME
# interviewer ("Vikram", pragmatic fintech lead) three sessions running. Diversity the
# model cannot observe must be supplied by us — hence per-session dials + a drawn name.

def test_kickoff_draws_a_different_interviewer_name_across_sessions():
    names = {p.build_kickoff(_cfg(), seed=s) for s in range(8)}
    assert len(names) > 1, "every session produced an identical kickoff"
    # A concrete name is ASSIGNED (not requested) — the model can't recall its default.
    k = p.build_kickoff(_cfg(), seed=1)
    assert "YOUR NAME THIS SESSION IS" in k
    assert any(n in k for n in p._NAMES_F + p._NAMES_M)


def test_interviewer_name_is_gender_matched_to_the_voice():
    fem = p.build_kickoff(_cfg(voice="female"), seed=3)
    male = p.build_kickoff(_cfg(voice="male"), seed=3)
    assert any(n in fem for n in p._NAMES_F)
    assert any(n in male for n in p._NAMES_M)


def test_kickoff_dials_vary_and_outrank_the_flavor_examples():
    a = p.build_kickoff(_cfg(), seed=1)
    b = p.build_kickoff(_cfg(), seed=2)
    assert "THIS SESSION'S DIALS" in a
    assert a != b, "dials did not vary across sessions"
    # The sector-matching trap that actually caused the collapse is called out.
    assert "IS the copying failure" in a
    assert "dials above outrank the examples" in a


def test_kickoff_bans_stock_pleasantry_openings():
    k = p.build_kickoff(_cfg())
    assert "stock pleasantry" in k


# ── Parsing degrades gracefully — a session must never fail to start ────────

def test_parse_kickoff_json():
    ident, opening = p.parse_kickoff('{"identity": "brisk fintech lead", "opening": "Asha, lets dig in."}')
    assert ident == "brisk fintech lead"
    assert opening == "Asha, lets dig in."


def test_parse_kickoff_strips_fences():
    ident, opening = p.parse_kickoff('```json\n{"identity":"warm mentor","opening":"Hi Asha."}\n```')
    assert ident == "warm mentor" and opening == "Hi Asha."


def test_parse_kickoff_falls_back_to_plain_text():
    # No JSON at all -> treat the whole reply as the opening, carry no identity.
    ident, opening = p.parse_kickoff("Hi Asha, tell me about a dashboard you built.")
    assert ident == ""
    assert opening.startswith("Hi Asha")
    # Empty / garbage never explodes.
    assert p.parse_kickoff("") == ("", "")


# ── The identity is replayed on every later turn ────────────────────────────

def test_identity_replayed_into_system_prompt():
    sp = p.build_system_prompt(_cfg(interviewer_identity="dry, fast panel lead; short acks"))
    assert "dry, fast panel lead" in sp
    assert "STAY IN IT" in sp
    assert "never changes difficulty" in sp.lower()


def test_system_prompt_without_identity_still_demands_a_consistent_persona():
    sp = p.build_system_prompt(_cfg())
    assert "YOUR IDENTITY" in sp
    assert "not a generic assistant" in sp


def test_system_prompt_has_no_fixed_greeting_template():
    sp = p.build_system_prompt(_cfg())
    # The old templated warm-up ("give a calming cue") must be gone.
    assert "calming cue" not in sp
    assert "open in YOUR identity" in sp


# ── Spoken rating / re-ask utility lines ───────────────────────────────────

def test_rating_ask_stable_per_seed_and_varied_across_seeds():
    assert p.rating_ask(3) == p.rating_ask(3)          # stable for one answer
    assert len({p.rating_ask(i) for i in range(4)}) > 1  # varies across the session
    assert all("one to five" in p.rating_ask(i).lower() for i in range(4))


def test_reask_lines_vary_and_never_add_a_question():
    assert len({p.reask_line(i) for i in range(4)}) > 1
    assert "do NOT ask a new question" in p.REASK_DIRECTIVE
    assert "never heard it" in p.REASK_DIRECTIVE


# ── Item 4/8: the quiet-mic and noise-coaching nudges ──────────────────────

def test_quiet_mic_lines_offer_the_fork_and_never_blame_the_answer():
    lines = [p.quiet_mic_line(i) for i in range(4)]
    assert len(set(lines)) > 1                                   # varied across the session
    # Every fallback names the fix (get closer / type) — never a dead end.
    for ln in lines:
        low = ln.lower()
        assert "typ" in low or "closer" in low or "nearer" in low or "close" in low
    # The directive tells IQ not to comment on an answer she never heard.
    assert "never heard it" in p.QUIET_MIC_DIRECTIVE
    assert "type" in p.QUIET_MIC_DIRECTIVE.lower()


def test_noise_lines_coach_the_room_never_the_person_and_never_the_score():
    lines = [p.noise_line(i) for i in range(4)]
    assert len(set(lines)) > 1
    for ln in lines:
        assert "quiet" in ln.lower() or "noise" in ln.lower() or "type" in ln.lower()
    # The environment must never bleed into judgement.
    assert "NEVER affect" in p.NOISE_DIRECTIVE or "never affect" in p.NOISE_DIRECTIVE.lower()


# ── Item 9: transcripts are speech, and the scorer is told so ───────────────

def test_debrief_never_penalises_transcription_or_indian_english():
    text = p.DEBRIEF_INSTRUCTION
    assert "SPEECH" in text
    low = text.lower()
    assert "spelling" in low and "punctuation" in low
    assert "indian english" in low
    # Quotes may be lightly cleaned but never have their meaning changed.
    assert "meaning" in low
