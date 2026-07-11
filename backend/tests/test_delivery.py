"""Unit tests for Voice Phase 3 delivery metrics (app/delivery.py).

Pure/offline: wpm + pace bands, filler counting (incl. Hinglish + phrases), pause
detection from timestamps, graceful nulls, client-payload sanitization, and the
readout aggregation (band + <3-answers guard).

Runnable with either:  python -m pytest tests/test_delivery.py
                  or:  python tests/test_delivery.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import delivery as d  # noqa: E402


# ── wpm + pace ──────────────────────────────────────────────────────────────

def test_wpm_and_pace_bands():
    # 30 words in 12s -> 150 wpm -> on_pace (sweet spot 130-160).
    m = d.compute(" ".join(["word"] * 30), 12.0)
    assert m["wpm"] == 150
    assert m["pace"] == "on_pace"
    # 20 words in 20s -> 60 wpm -> slow.
    assert d.compute(" ".join(["w"] * 20), 20.0)["pace"] == "slow"
    # 80 words in 20s -> 240 wpm -> rushed.
    assert d.compute(" ".join(["w"] * 80), 20.0)["pace"] == "rushed"


def test_wpm_none_on_bad_duration():
    m = d.compute("some real words here that are fine", 0)
    assert m["wpm"] is None and m["pace"] is None
    assert m["filler_count"] == 0  # still computes text-based metrics


def test_none_on_empty_transcript():
    assert d.compute("", 10) is None
    assert d.compute("   ", 10) is None


# ── fillers (single words, phrases, Hinglish) ───────────────────────────────

def test_filler_counting():
    text = "Um, so basically I, uh, you know, matlab woh thing, like actually yes."
    total, per = d.count_fillers(text)
    assert per.get("um") == 1
    assert per.get("uh") == 1
    assert per.get("you know") == 1
    assert per.get("basically") == 1
    assert per.get("matlab") == 1
    assert per.get("woh") == 1
    assert per.get("like") == 1
    assert per.get("actually") == 1
    assert total == 8


def test_filler_does_not_match_substrings():
    # "likely" must not count as "like"; "outing" must not count as "um"/"uh".
    _, per = d.count_fillers("It is likely an outing, summarised umbrella notwithstanding.")
    assert "like" not in per


# ── pauses from timestamps ──────────────────────────────────────────────────

def test_long_pauses_counts_between_segment_gaps():
    ts = {
        "words": ["first part", "second part", "third part"],
        "start_time_seconds": [0.0, 5.0, 6.0],   # 5.0-3.0 = 2s gap (not >2); 6.0-5.5=0.5
        "end_time_seconds": [3.0, 5.5, 9.0],
    }
    # gap1 = 5.0 - 3.0 = 2.0 (not > 2.0). gap2 = 6.0 - 5.5 = 0.5. -> 0 long pauses.
    assert d.long_pauses(ts) == 0
    ts2 = {"start_time_seconds": [0.0, 6.0], "end_time_seconds": [3.0, 9.0]}  # gap 3.0s
    assert d.long_pauses(ts2) == 1


def test_long_pauses_none_when_single_segment_or_missing():
    # Single whole-utterance segment (what saarika:v2.5 returned in probing) -> None.
    assert d.long_pauses({"start_time_seconds": [0.0], "end_time_seconds": [5.0]}) is None
    assert d.long_pauses(None) is None
    assert d.long_pauses({}) is None


# ── sanitize (untrusted client echo) ────────────────────────────────────────

def test_sanitize_keeps_known_fields_drops_junk():
    raw = {
        "wpm": 140, "pace": "on_pace", "filler_count": 2, "filler_per_min": 3.5,
        "fillers": {"um": 2, "notafiller": 9, "like": 0}, "long_pause_count": 1,
        "word_count": 40, "articulation": None,
        "evil": "DROP TABLE", "overall_band": "Offer-Ready",  # must be dropped
    }
    clean = d.sanitize(raw)
    assert clean["wpm"] == 140 and clean["pace"] == "on_pace"
    assert clean["fillers"] == {"um": 2}          # unknown + zero-count dropped
    assert "evil" not in clean and "overall_band" not in clean
    assert d.sanitize({"pace": "bogus"}) is None  # nothing usable
    assert d.sanitize("not a dict") is None


# ── aggregation for the readout ─────────────────────────────────────────────

def _m(wpm, fillers=None, fpm=0.0, pauses=None):
    return {"wpm": wpm, "filler_per_min": fpm, "fillers": fillers or {},
            "long_pause_count": pauses}


def test_aggregate_needs_three_spoken_answers():
    prof = d.aggregate([_m(150), _m(150)])
    assert prof["enough_data"] is False
    assert "Not enough voice data" in prof["message"]
    assert "delivery_band" not in prof


def test_aggregate_produces_band_and_top_fillers():
    metrics = [
        _m(150, {"um": 3, "like": 1}, fpm=2.0, pauses=0),
        _m(150, {"um": 2, "basically": 2}, fpm=2.0, pauses=0),
        _m(150, {"like": 3}, fpm=2.0, pauses=0),
    ]
    prof = d.aggregate(metrics)
    assert prof["enough_data"] is True
    assert prof["avg_wpm"] == 150
    assert "sweet spot" in prof["pace_verdict"]
    # top 2 offenders by total count: um=5, like=4 (basically=2).
    assert prof["top_fillers"][0] == ("um", 5)
    assert prof["top_fillers"][1] == ("like", 4)
    # clean pace + low fillers + no pauses -> top band.
    assert prof["delivery_band"] == "Offer-Ready"
    assert "not counted in your readiness band" in prof["note"]


def test_aggregate_penalises_rushed_and_fillers():
    metrics = [_m(240, {"um": 10}, fpm=12.0, pauses=3) for _ in range(3)]
    prof = d.aggregate(metrics)
    # 100 - 25 (rushed) - 30 (>8 fpm) - min(3*5,20)=15 = 30 -> Not Ready.
    assert prof["delivery_score"] == 30
    assert prof["delivery_band"] == "Not Ready"


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
