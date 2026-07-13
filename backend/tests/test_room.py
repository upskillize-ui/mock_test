"""Interview Room — focus signals, escalation ladder, device policy, early wrap.

Guards the things that must NOT regress:
  * PRIVACY   — the event surface is strings only; there is no media path.
  * FAIRNESS  — a camera-off join is never penalised, and the word "cheating" never
                appears in any user-facing string.
  * HONESTY   — no emotion/personality words anywhere in the readout copy.
  * SAFETY    — an early wrap still scores the rounds that were completed.

Runnable with:  python -m pytest tests/test_room.py
"""
import os
import re
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import presence as pr  # noqa: E402
from app import prompts as p  # noqa: E402
from app import stages as s  # noqa: E402


# ── The signal surface is strings, and nothing else ─────────────────────────

def test_event_type_set_is_closed():
    assert pr.is_valid_event("tab_hidden")
    assert pr.is_valid_event("camera_off")
    assert not pr.is_valid_event("frame")          # there is no media path, by design
    assert not pr.is_valid_event("screenshot")
    assert not pr.is_valid_event("")


def test_non_camera_signals_work_without_a_camera():
    # tab/window signals need no camera, so they apply on EVERY join path.
    for t in pr.NON_CAMERA_SIGNALS:
        assert pr.accepts_event(t, camera_at_join=False)


# ── Fairness: a camera-off join is never penalised ─────────────────────────

def test_camera_signals_ignored_when_joined_camera_off():
    for t in pr.CAMERA_SIGNALS:
        assert pr.accepts_event(t, camera_at_join=True)
        assert not pr.accepts_event(t, camera_at_join=False)


def test_readout_omits_camera_lines_for_a_camera_off_join():
    by_type = {"looking_away": 5, "no_face": 2, "tab_hidden": 1}
    out = pr.presence_readout(by_type, camera_at_join=False)
    # The camera signals were never measured -> never reported, never counted.
    assert "looking_away" not in out["by_type"]
    assert "no_face" not in out["by_type"]
    assert out["by_type"] == {"tab_hidden": 1}
    assert out["events_total"] == 1
    assert out["camera_signals_disabled"] is True

    # With the camera on at join, the same events DO count.
    on = pr.presence_readout(by_type, camera_at_join=True)
    assert on["events_total"] == 8


def test_camera_ladder_never_fires_for_a_camera_off_join():
    assert pr.camera_ladder_action(9, camera_at_join=False) == "none"


# ── Debounce ───────────────────────────────────────────────────────────────

def test_debounce_window():
    assert pr.within_debounce(0) is True
    assert pr.within_debounce(29.9) is True
    assert pr.within_debounce(30) is False
    assert pr.within_debounce(None) is False      # no previous event -> accept
    assert pr.within_debounce("junk") is False    # never explode on bad input


# ── Escalation ladder ──────────────────────────────────────────────────────

def test_escalation_level_transitions():
    assert pr.escalation_level(0) == 0
    assert pr.escalation_level(1) == 1
    assert pr.escalation_level(2) == 1     # first 2 -> gentle
    assert pr.escalation_level(3) == 2
    assert pr.escalation_level(4) == 2     # 3rd-4th -> firm
    assert pr.escalation_level(5) == 3
    assert pr.escalation_level(50) == 3    # 5+ -> noted in feedback


def test_escalation_directives_are_coaching_not_punishment():
    assert pr.escalation_directive(0) == ""   # silence is the default
    for lvl in (1, 2, 3):
        d = pr.escalation_directive(lvl).lower()
        assert d
        # The word must not even appear in the PROMPT — naming it primes the model to
        # echo it. (This test caught exactly that in the first draft.)
        assert "cheat" not in d
        # Never script the line — the improvised persona supplies the words.
        assert "in your own voice" in d
        # The ladder changes TONE, never the interview itself.
        assert "carry on with the interview exactly as planned" in d


def test_camera_ladder_transitions():
    assert pr.camera_ladder_action(0, True) == "none"
    assert pr.camera_ladder_action(1, True) == "nudge"
    assert pr.camera_ladder_action(2, True) == "warn"
    assert pr.camera_ladder_action(3, True) == "wrap"
    assert pr.camera_ladder_action(7, True) == "wrap"


# ── Honesty: no emotion / personality / accusation language anywhere ────────

BANNED = ("cheat", "dishonest", "suspicious", "lying", "liar",
          "happy", "sad", "angry", "nervous", "emotion", "confident person",
          "personality", "attitude problem")


def _user_facing_strings():
    """Everything a CANDIDATE could actually read or hear. The persona prompt is NOT in
    here on purpose: PART 1 requires it to name the forbidden words in order to forbid
    them ("Never say nervous, bored …"). A literal token-ban would make the rule
    unstateable. What actually harms is the ATTRIBUTION PATTERN — tested separately
    below, across the prompts too."""
    out = list(pr._COACHING.values())
    out += [pr.presence_readout({}, True)["coaching_note"]]
    out += [pr.presence_readout({"looking_away": 9}, True)["coaching_note"]]
    out += [pr.presence_readout({"tab_hidden": 3}, True)["coaching_note"]]
    return out


def test_no_banned_language_in_any_user_facing_presence_copy():
    strings = _user_facing_strings()
    # Directives are model instructions, but they must ALSO stay clean of these tokens.
    strings += [pr.escalation_directive(i) for i in (1, 2, 3)]
    strings += [pr.camera_directive(a) for a in ("nudge", "warn")]
    strings += [pr.wrap_directive()]
    for text in strings:
        low = text.lower()
        for bad in BANNED:
            assert bad not in low, f"banned word {bad!r} in: {text[:70]}"


# ── The attribution PATTERN is the real harm — ban it everywhere, prompts included ──
# "your gaze drifted; try holding it" is coaching. "you seemed bored" is a claim about a
# person's inner state that we cannot possibly support. Only the second is forbidden.

EMOTION_WORDS = (
    "bored", "nervous", "disinterested", "uninterested", "anxious", "sad", "scared",
    "unconfident", "uncomfortable", "distracted", "upset", "angry", "unhappy",
    "disengaged", "low.energy",
)
ATTRIBUTION_RX = re.compile(
    r"\b(you|they|he|she|the candidate)\s+"
    r"(were|was|are|is|seem\w*|look\w*|felt|feel\w*|appear\w*|come across as)\b"
    r"[^.?!]{0,40}?\b(" + "|".join(EMOTION_WORDS) + r")\b",
    re.IGNORECASE,
)


def test_no_emotion_attribution_pattern_anywhere():
    """Describe observable behaviour; never claim an inner state. This scans the PROMPTS
    too — the persona may NAME these words to forbid them, but must never USE them as an
    attribution ("you seemed bored")."""
    blobs = _user_facing_strings()
    blobs += [pr.escalation_directive(i) for i in (0, 1, 2, 3)]
    blobs += [pr.camera_directive(a) for a in ("none", "nudge", "warn")]
    blobs += [pr.wrap_directive()]
    cfg = {"name": "Asha", "role": "Backend Engineer", "level": "Fresher",
           "company": "Razorpay", "duration_min": 20, "difficulty": "Realistic",
           "interviewer_name": "Priya", "focus": [], "intro": "", "mode": "interview",
           "round": "full"}
    blobs += [p.build_persona(cfg), p.build_system_prompt(cfg),
              p.stage_turn_directive(cfg, "DOMAIN", 1)]
    for text in blobs:
        m = ATTRIBUTION_RX.search(text or "")
        assert not m, f"emotion attribution {m.group(0)!r} in: {text[:80]}"


def test_the_attribution_pattern_test_actually_catches_the_bad_shape():
    # Guard the guard — a test that can never fail is worthless.
    assert ATTRIBUTION_RX.search("Honestly, you seemed a bit bored in that round.")
    assert ATTRIBUTION_RX.search("The candidate was clearly nervous.")
    assert ATTRIBUTION_RX.search("You felt uncomfortable there.")
    # ...and that legitimate behavioural coaching passes cleanly.
    assert not ATTRIBUTION_RX.search("Your gaze drifted off-camera; hold the interviewer's eye.")
    assert not ATTRIBUTION_RX.search("You looked away on 40% of the case question.")
    assert not ATTRIBUTION_RX.search("Never say nervous, bored, disinterested or anxious.")


def test_presence_band_is_counts_only():
    assert pr.presence_band(0) == "Offer-Ready"
    assert pr.presence_band(2) == "Interview-Ready"
    assert pr.presence_band(4) == "Building"
    assert pr.presence_band(5) == "Not Ready"


# ── Early wrap: end the interview, never the score ─────────────────────────

def test_early_wrap_transition_goes_to_readout_and_remembers_where():
    new_stage, at = s.early_wrap_transition("DOMAIN")
    assert new_stage == "READOUT"      # -> next_action "readout" -> the debrief runs
    assert at == "DOMAIN"
    # READOUT is terminal input-wise, so a refresh lands on the readout, not the room.
    assert s.next_action("READOUT", False) == "readout"


def test_early_wrap_does_not_zero_anything():
    # The wrap only moves the stage. Scoring runs over the rounds actually completed —
    # there is no code path here that discards or zeroes an answer.
    assert s.early_wrap_transition("CASE") == ("READOUT", "CASE")
    assert s.band_for(72) == "Interview-Ready"   # bands still behave normally


# ── The persona ADOPTS the face the student can see ────────────────────────

def test_interviewer_name_from_the_client_roster_is_adopted():
    cfg = {"name": "Asha", "role": "Backend Engineer", "level": "Fresher",
           "company": "Razorpay", "duration_min": 20, "voice": "female",
           "interviewer_name": "Priya"}
    k = p.build_kickoff(cfg, seed=1)
    assert "YOUR NAME THIS SESSION IS Priya" in k


def test_server_draws_a_name_when_the_client_omits_one():
    cfg = {"name": "Asha", "role": "Backend Engineer", "level": "Fresher",
           "company": "Razorpay", "duration_min": 20, "voice": "male"}
    k = p.build_kickoff(cfg, seed=1)
    assert "YOUR NAME THIS SESSION IS" in k
    assert any(n in k for n in p._NAMES_M)      # classic-mode fallback still works


# ── The presence note rides the turn as TONE, never as difficulty ──────────

def test_presence_note_is_prepended_to_the_turn_directive():
    cfg = {"level": "Fresher", "role": "Backend Engineer", "name": "Asha"}
    note = pr.escalation_directive(2)
    with_note = p.stage_turn_directive(cfg, "DOMAIN", 1, presence_note=note)
    without = p.stage_turn_directive(cfg, "DOMAIN", 1)
    assert with_note.startswith(note.strip())
    # The round plan underneath is byte-identical — the ladder never changes the interview.
    assert with_note.endswith(without)
