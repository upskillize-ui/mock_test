"""Unit tests for the InterviewIQ stage machine, bands and calibration (stages.py).

Runnable with either:  python -m pytest tests/test_stages.py
                  or:  python tests/test_stages.py
Requires only the standard settings env vars to import config.
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import stages as s  # noqa: E402


def test_stage_plan_by_level():
    fresher = s.stage_plan("Fresher")
    assert fresher["totals"] == {"WARMUP": 2, "DOMAIN": 4, "BEHAVIOURAL": 3, "CASE": 1, "REVERSE": 2}
    assert fresher["case_variant"] == "short"
    assert fresher["notice_period"] is False

    senior = s.stage_plan("20+ years")
    assert senior["totals"]["DOMAIN"] == 6
    assert senior["totals"]["BEHAVIOURAL"] == 4
    assert senior["case_variant"] == "long"
    assert senior["notice_period"] is True


def test_stage_order_and_advancement():
    # WARMUP question 1 -> stay; question 2 -> advance to DOMAIN.
    assert s.advance_after_rating("WARMUP", 1, "Fresher") == ("WARMUP", 1)
    assert s.advance_after_rating("WARMUP", 2, "Fresher") == ("DOMAIN", 0)
    # DOMAIN(4) complete -> BEHAVIOURAL; BEHAVIOURAL(3) complete -> CASE; CASE(1) -> REVERSE.
    assert s.advance_after_rating("DOMAIN", 4, "Fresher") == ("BEHAVIOURAL", 0)
    assert s.advance_after_rating("BEHAVIOURAL", 3, "Fresher") == ("CASE", 0)
    assert s.advance_after_rating("CASE", 1, "Fresher") == ("REVERSE", 0)
    # REVERSE is not rating-gated; 2 questions -> READOUT.
    assert s.advance_after_reverse(1, "Fresher") == ("REVERSE", 1)
    assert s.advance_after_reverse(2, "Fresher") == ("READOUT", 0)


def test_next_action():
    assert s.next_action("WARMUP", False) == "answer"
    assert s.next_action("WARMUP", True) == "rating"
    assert s.next_action("REVERSE", False) == "reverse_question"
    assert s.next_action("READOUT", False) == "readout"
    assert s.next_action("DONE", False) == "done"


def test_bands_at_boundaries():
    assert s.band_for(49) == "Not Ready"
    assert s.band_for(50) == "Building"
    assert s.band_for(69) == "Building"
    assert s.band_for(70) == "Interview-Ready"
    assert s.band_for(84) == "Interview-Ready"
    assert s.band_for(85) == "Offer-Ready"
    assert s.band_for(None) == "Not Ready"


def test_calibration_categories():
    assert s.calibration_profile([(5, 1), (4, 2), (5, 2)])["profile"] == "over_confident"
    assert s.calibration_profile([(1, 5), (2, 4)])["profile"] == "under_confident"
    assert s.calibration_profile([(3, 3), (4, 4)])["profile"] == "well_calibrated"
    # null ratings excluded -> insufficient data, no crash.
    assert s.calibration_profile([(None, 3), (None, 2)])["profile"] == "insufficient_data"


def test_calibration_numbers_and_tie_break():
    prof = s.calibration_profile([(5, 1), (4, 3)])
    assert prof["avg_confidence"] == 4.5
    assert prof["avg_score"] == 2.0
    assert prof["calibration_delta"] == 2.5
    # tie between over and under -> prefer over_confident (the pattern we flag).
    assert s.calibration_profile([(5, 1), (1, 5)])["profile"] == "over_confident"


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
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
