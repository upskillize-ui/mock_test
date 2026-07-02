"""InterviewIQ session-stage machine, readiness bands, and calibration math.

Pure logic only (no DB, no I/O) so it is trivially testable. Consumed by main.py.

Stages (INT-04):
  SETUP -> WARMUP -> DOMAIN -> BEHAVIOURAL -> CASE -> REVERSE -> READOUT -> DONE

The learner answers questions in WARMUP/DOMAIN/BEHAVIOURAL/CASE (these are
"scored" stages and each answer is followed by a confidence rating, INT-01).
REVERSE flips the flow: the learner asks the interviewer questions (not rated).
READOUT is terminal input-wise; the debrief is generated at /session/end.
"""

from .config import settings

# Ordered, answerable stages (excludes SETUP/READOUT/DONE which take no /turn answer).
STAGE_ORDER = ["WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE", "REVERSE"]
SCORED_STAGES = {"WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE"}
TERMINAL_STAGES = {"READOUT", "DONE"}

STAGE_LABELS = {
    "WARMUP": "Warm-up",
    "DOMAIN": "Domain",
    "BEHAVIOURAL": "Behavioural",
    "CASE": "Case",
    "REVERSE": "Your Questions",
    "READOUT": "Readout",
    "DONE": "Complete",
}


def _seniority_bucket(level: str) -> str:
    """Map the frontend's experience-level strings to a question-count bucket.

    Buckets: 'fresher' | 'junior' (0-2) | 'mid' (2-5) | 'senior' (5+).
    """
    lv = (level or "").strip().lower()
    if lv in ("fresher", "0-2", "student", "intern"):
        return "fresher"
    if lv in ("career switcher", "1-3 years", "0-1 year", "< 1 year"):
        return "junior"
    if lv in ("3-10 years", "2-5", "mid"):
        return "mid"
    if lv in ("10-20 years", "20+ years", "5+", "senior"):
        return "senior"
    # Unknown -> treat as mid (safe middle ground).
    return "mid"


def stage_plan(level: str) -> dict:
    """Return the per-stage question targets + flags for this experience level."""
    bucket = _seniority_bucket(level)
    if bucket == "fresher":
        domain, behavioural, case_variant, notice = 4, 3, "short", False
    elif bucket == "junior":
        domain, behavioural, case_variant, notice = 4, 3, "short", False
    elif bucket == "senior":
        domain, behavioural, case_variant, notice = 6, 4, "long", True
    else:  # mid
        domain, behavioural, case_variant, notice = 5, 3, "long", False
    return {
        "bucket": bucket,
        "totals": {
            "WARMUP": 2,
            "DOMAIN": domain,
            "BEHAVIOURAL": behavioural,
            "CASE": 1,
            "REVERSE": 2,
        },
        "case_variant": case_variant,
        "notice_period": notice,
    }


def stage_total(level: str, stage: str) -> int:
    return stage_plan(level)["totals"].get(stage, 0)


def next_stage(stage: str) -> str:
    """The stage that follows `stage`. After REVERSE comes READOUT; then DONE."""
    if stage in TERMINAL_STAGES:
        return "DONE" if stage == "READOUT" else "DONE"
    try:
        idx = STAGE_ORDER.index(stage)
    except ValueError:
        return "READOUT"
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else "READOUT"


def is_scored(stage: str) -> bool:
    return stage in SCORED_STAGES


def stage_label(stage: str, round_index: int, level: str, awaiting_rating: bool = False) -> str:
    """Human progress label, e.g. 'Behavioural · Question 2 of 4'."""
    name = STAGE_LABELS.get(stage, stage.title())
    if stage in TERMINAL_STAGES:
        return name
    total = stage_total(level, stage)
    # While rating, we reference the answer just given (round_index already
    # incremented). While answering, we reference the upcoming question.
    qnum = round_index if awaiting_rating else round_index + 1
    qnum = max(1, min(qnum, total))
    return f"{name} · Question {qnum} of {total}"


def next_action(current_stage: str, awaiting_rating: bool) -> str:
    """What the client should do next: answer | rating | reverse_question | readout | done."""
    if current_stage == "DONE":
        return "done"
    if current_stage == "READOUT":
        return "readout"
    if awaiting_rating:
        return "rating"
    if current_stage == "REVERSE":
        return "reverse_question"
    return "answer"


def advance_after_rating(current_stage: str, round_index: int, level: str) -> tuple[str, int]:
    """Called once a rating is recorded. If the current scored stage is complete,
    move to the next stage and reset the per-stage counter."""
    if round_index >= stage_total(level, current_stage):
        return next_stage(current_stage), 0
    return current_stage, round_index


def advance_after_reverse(round_index: int, level: str) -> tuple[str, int]:
    """REVERSE is not rating-gated; advance straight to READOUT when complete."""
    if round_index >= stage_total(level, "REVERSE"):
        return "READOUT", 0
    return "REVERSE", round_index


# ── INT-03: readiness bands ────────────────────────────────────────────────

def band_for(pct) -> str:
    """Map a 0-100 score to a canonical InterviewIQ readiness band."""
    if pct is None:
        return "Not Ready"
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "Not Ready"
    if p >= settings.BAND_OFFER_READY_MIN:
        return "Offer-Ready"
    if p >= settings.BAND_INTERVIEW_READY_MIN:
        return "Interview-Ready"
    if p >= settings.BAND_BUILDING_MIN:
        return "Building"
    return "Not Ready"


def round_bands_from_scores(round_scores: dict) -> dict:
    """round_scores: {'domain': 0-100, ...} -> {'domain': 'Building', ...}."""
    out = {}
    if not isinstance(round_scores, dict):
        return out
    for key, val in round_scores.items():
        if val is None:
            continue
        out[key] = band_for(val)
    return out


# ── INT-02: calibration ────────────────────────────────────────────────────

def _categorize(rating: int, score_1_5: float) -> str:
    """Classify one rated answer. Score is already normalised to 1-5."""
    delta = rating - score_1_5
    if abs(delta) <= 1:
        return "well_calibrated"
    if rating >= 4 and score_1_5 <= 2:
        return "over_confident"
    if rating <= 2 and score_1_5 >= 4:
        return "under_confident"
    # Outside the tight band but not an extreme mismatch: lean by direction.
    if delta > 0:
        return "over_confident"
    if delta < 0:
        return "under_confident"
    return "well_calibrated"


def calibration_profile(pairs: list[tuple]) -> dict:
    """pairs: ordered list of (rating_or_None, score_1_5) for scored answers.

    Returns the session calibration profile. Null-rating answers are excluded.
    """
    rated = [(r, s) for (r, s) in pairs if r is not None and s is not None]
    if not rated:
        return {
            "profile": "insufficient_data",
            "avg_confidence": None,
            "avg_score": None,
            "calibration_delta": None,
            "per_answer": [],
            "rated_count": 0,
        }

    per_answer = []
    counts = {"well_calibrated": 0, "over_confident": 0, "under_confident": 0}
    conf_sum = 0.0
    score_sum = 0.0
    for rating, score in rated:
        cat = _categorize(rating, score)
        counts[cat] += 1
        conf_sum += rating
        score_sum += score
        per_answer.append({"rating": rating, "score": round(float(score), 1), "category": cat})

    n = len(rated)
    avg_conf = conf_sum / n
    avg_score = score_sum / n

    # Modal category; tie -> over_confident (the pattern we most want to flag).
    top = max(counts.values())
    if counts["over_confident"] == top:
        profile = "over_confident"
    elif counts["under_confident"] == top and counts["under_confident"] > counts["well_calibrated"]:
        profile = "under_confident"
    elif counts["well_calibrated"] == top:
        profile = "well_calibrated"
    else:
        profile = "over_confident"

    return {
        "profile": profile,
        "avg_confidence": round(avg_conf, 1),
        "avg_score": round(avg_score, 1),
        "calibration_delta": round(avg_conf - avg_score, 1),
        "per_answer": per_answer,
        "rated_count": n,
    }
