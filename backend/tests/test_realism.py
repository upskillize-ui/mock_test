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
    k = p.build_kickoff(_cfg())
    # The opening is capped at 2-3 sentences — the SAME limit the persona puts on every
    # other turn ("2-3 SHORT sentences per turn, then STOP"). It used to allow four, and
    # measured openings were running to five: a paragraph delivered at someone who has just
    # sat down, which is neither what a person does nor what we told the model to do
    # everywhere else. Tightening it also happens to be worth ~0.6s of the start latency,
    # because those are tokens a candidate is sitting there waiting for.
    assert "2 or 3 SHORT sentences" in k
    assert "Not four" in k
    # Must land on a real, role-shaped first question (not generic rapport).
    assert "shaped by the" in k and "tell me about yourself" in k.lower()
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
