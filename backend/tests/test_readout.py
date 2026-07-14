"""E6 — the readout: what it says first, and in whose voice.

The order IS the coaching. A struggling learner used to open the page on a label
("Not Ready") with the reasons buried underneath, which is the one shape guaranteed not
to be read. Now: what went well, in their own words -> how they came across -> the two or
three fixes that matter, each with something to do about it tomorrow -> and only then the
verdict, with their own confidence ratings held up against it.

Runnable with:  python -m pytest tests/test_readout.py
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

from app import prompts as p  # noqa: E402
from app import stages as s  # noqa: E402

D = p.DEBRIEF_INSTRUCTION


# ── The order of the readout is deliberate, so pin it ──────────────────────

def test_the_readout_leads_with_what_went_well_and_ends_with_the_verdict():
    well = D.index("WHAT WENT WELL")
    across = D.index("HOW THEY CAME ACROSS")
    fixes = D.index("THE 2-3 FIXES THAT MATTER")
    verdict = D.index("THE VERDICT")
    assert well < across < fixes < verdict, "the readout order is the coaching — do not reshuffle it"


def test_strengths_must_quote_the_candidate():
    # A readout that could have been written without listening to THIS person is worthless.
    assert '"evidence"' in D
    assert "QUOTE THEIR OWN WORDS BACK TO THEM" in D
    assert "Generic praise" in D


def test_no_answers_means_no_strengths_to_invent():
    assert "strengths MUST be an empty list" in D


def test_every_fix_carries_something_to_do_about_it():
    assert '"tryThisNextTime"' in D
    assert "EXACTLY 2 or 3" in D
    # An action for tomorrow, not a subject to go away and study.
    assert "never a subject to go away and study" in D


def test_the_voice_is_a_mentor_talking_to_them_not_about_them():
    assert 'Write to THEM ("you")' in D
    assert "No praise sandwiches" in D
    # Behaviour, never inner state — the same line the persona and presence engines hold.
    assert "never what they felt" in D


# ── The calibration delta, explained in one sentence ───────────────────────

def _cal(ratings_and_scores):
    return s.calibration_profile(ratings_and_scores)


def test_the_band_block_gets_one_sentence_explaining_the_delta():
    over = _cal([(5, 1), (5, 2), (4, 2)])
    assert over["profile"] == "over_confident"
    sent = over["sentence"]
    # ONE sentence, not a lecture. (Counting "." would trip over the decimals in "4.7/5",
    # so we check for a sentence BREAK instead: a full stop followed by a space.)
    assert sent and sent.endswith(".") and ". " not in sent
    assert str(abs(over["calibration_delta"])) in sent   # the actual number, not a vibe
    assert f'{over["avg_confidence"]}/5' in sent
    assert f'{over["avg_score"]}/5' in sent


def test_each_profile_says_something_different_and_useful():
    under = _cal([(1, 5), (2, 4)])["sentence"]
    over = _cal([(5, 1), (4, 2)])["sentence"]
    well = _cal([(3, 3), (4, 4)])["sentence"]
    assert under and over and well
    assert len({under, over, well}) == 3
    # Under-confidence is a real cost, and it is named as one — never as a personal flaw.
    assert "marking yourself down" in under
    assert "thinner than it feels" in over


def test_no_ratings_means_no_sentence_rather_than_a_made_up_one():
    assert _cal([])["sentence"] == ""
    assert _cal([(None, 3), (None, 2)])["sentence"] == ""
    assert s.calibration_sentence({}) == ""
    assert s.calibration_sentence({"profile": "insufficient_data"}) == ""


# The same rule the presence engine holds: describe what they DID, never claim what they
# ARE or FELT. This is the sentence a struggling learner reads next to their band, so it
# is the last place we can afford to get it wrong.
EMOTION_ATTRIBUTION = re.compile(
    r"\b(you|they)\s+(were|was|are|is|seem\w*|look\w*|felt|feel\w*|appear\w*)\b"
    r"[^.?!]{0,40}?\b(nervous|anxious|bored|arrogant|unconfident|insecure|weak)\b",
    re.IGNORECASE,
)


def test_the_calibration_sentence_never_tells_them_who_they_are():
    for pairs in ([(5, 1), (4, 2)], [(1, 5), (2, 4)], [(3, 3), (4, 4)]):
        sent = _cal(pairs)["sentence"]
        assert not EMOTION_ATTRIBUTION.search(sent), sent
        for banned in ("over-confident person", "arrogant", "insecure"):
            assert banned not in sent.lower()
