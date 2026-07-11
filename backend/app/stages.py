"""InterviewIQ session-stage machine, readiness bands, and calibration math.

Pure logic only (no DB, no I/O) so it is trivially testable. Consumed by main.py.

Stages (INT-04):
  SETUP -> WARMUP -> DOMAIN -> BEHAVIOURAL -> CASE -> REVERSE -> READOUT -> DONE

The learner answers questions in WARMUP/DOMAIN/BEHAVIOURAL/CASE (these are the
"scored" stages). Confidence ratings (INT-01) are collected from DOMAIN onward;
WARMUP is intentionally exempt — warm-up answers advance straight to the next
question. REVERSE flips the flow: the learner asks the interviewer questions
(not rated). READOUT is terminal input-wise; the debrief is at /session/end.
"""

import re

from .config import settings

# Ordered, answerable stages (excludes SETUP/READOUT/DONE which take no /turn answer).
STAGE_ORDER = ["WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE", "REVERSE"]
SCORED_STAGES = {"WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE"}
# Stages whose answers are followed by a confidence rating. WARMUP is excluded
# by product decision — warm-up is a rapport ice-breaker, not rating-gated.
RATING_STAGES = {"DOMAIN", "BEHAVIOURAL", "CASE"}
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


def is_rating_gated(stage: str) -> bool:
    """True if a learner answer in this stage must be followed by a confidence
    rating before the interview can proceed. WARMUP is not gated (INT-01 exemption)."""
    return stage in RATING_STAGES


# ── Substantive-answer gate (generalises the WARMUP rating exemption) ─────────
# We only ask a learner to rate their confidence, and only "spend" a question
# slot, on a *substantive* answer. A non-answer ("I don't know" / "skip" / a bare
# clarification request / a couple of characters) is not something worth rating,
# and it must not consume one of the round's planned questions.

MIN_SUBSTANTIVE_CHARS = 15

# Obvious non-answers. Anchored so we only fire on a message that is *entirely* a
# non-answer, not one that merely contains the phrase ("I don't know why, but the
# reason we chose Kafka was ..." is a real answer and must still be rated).
_NONANSWER_RX = re.compile(
    r"^\s*(i\s*(really\s*|honestly\s*)?(don'?t|do\s*not|dont)\s*know"
    r"|no\s*idea|not\s*sure|no\s*clue|dunno|idk"
    r"|skip(\s*this)?|pass|next(\s*question)?|move\s*on"
    r"|can'?t\s*answer|cannot\s*answer|i\s*give\s*up|no\s*comment)"
    r"[\s.!?]*$",
    re.IGNORECASE,
)
# Pure clarification requests — the learner asked us something instead of answering.
_CLARIFY_RX = re.compile(
    r"^\s*(what\s*do\s*you\s*mean"
    r"|(can|could)\s*you\s*(please\s*)?(repeat|rephrase|clarify|explain)"
    r"|come\s*again|sorry\s*,?\s*what|pardon|i\s*didn'?t\s*(get|understand))"
    # allow a short trailing tail ("...repeat that?", "...clarify the question please")
    # but not a whole sentence, so a genuine answer that clarifies-then-answers still rates.
    r"(\s+\w+){0,3}[\s.?!]*$",
    re.IGNORECASE,
)
# Meaningful characters = letters/digits (Latin + Devanagari for Hinglish typed in
# Hindi script); punctuation and whitespace don't count toward "did they say anything".
_NONMEANINGFUL_RX = re.compile(r"[^0-9a-zऀ-ॿ]")


def is_non_substantive(text: str) -> bool:
    """Cheap, deterministic guard — True when an answer is an obvious non-answer.

    Runs BEFORE any LLM judgement so we never burn a confidence-rating prompt on a
    "don't know" / "skip" / bare clarification, even if the scoring model would
    later misjudge it as substantive. Deliberately conservative: it only fires on
    clear non-answers, so genuine (even terse) answers still get rated, and the
    debrief scoring call's `substantive` flag catches the subtler cases.
    """
    if not text:
        return True
    stripped = text.strip()
    if _NONMEANINGFUL_RX.sub("", stripped.lower()).__len__() < MIN_SUBSTANTIVE_CHARS:
        return True
    return bool(_NONANSWER_RX.match(stripped) or _CLARIFY_RX.match(stripped))


def should_await_rating(stage: str, is_substantive: bool) -> bool:
    """True iff a just-submitted answer in `stage` must be rated before proceeding.

    Generalises the WARMUP exemption: rating-gated stages only (DOMAIN/BEHAVIOURAL/
    CASE), and only for substantive answers (FIX 1 — rate only substantive answers).
    """
    return is_rating_gated(stage) and is_substantive


def consumes_question_slot(stage: str, is_substantive: bool) -> bool:
    """FIX 2 — a non-substantive answer in a scored, rating-gated stage does NOT
    consume a planned question slot: the interviewer steps down / re-asks on the
    same topic instead, so 'a round of 4' still means 4 substantive questions.
    Every other turn (WARMUP, REVERSE, and all substantive answers) advances normally.
    """
    if is_rating_gated(stage) and not is_substantive:
        return False
    return True


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


def _coerce_int(v):
    """Best-effort int (the model may echo an id as a string or a float)."""
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _scores_by_answer_id(per_answer_scores: list, valid_answer_ids=None) -> dict:
    """INT-11: index the model's per-answer scores by the answer_id they echo.

    Only entries whose echoed answerId is a real answer (present in
    valid_answer_ids, when provided) are kept, so a hallucinated / duplicated id
    can't inject a bogus pair. Later entries win on a duplicate id.
    """
    out = {}
    for e in per_answer_scores or []:
        if not isinstance(e, dict):
            continue
        aid = _coerce_int(e.get("answerId"))
        if aid is None:
            continue
        if valid_answer_ids is not None and aid not in valid_answer_ids:
            continue
        out[aid] = e
    return out


def calibration_pairs(ratings: list, per_answer_scores: list, valid_answer_ids=None) -> list:
    """INT-11: join learner confidence ratings to model quality scores BY answer_id.

    ratings: ordered list of (answer_id, rating) — rating may be None ("prefer not
    to say"). per_answer_scores: the model's perAnswerScores, each echoing answerId.

    Returns ordered (rating, score) pairs for the answers that have BOTH a rating and
    a substantive score entry. Because the pairing is by id (not position), a
    non-substantive answer dropped from the middle of the list — or an extra/missing
    entry from the model — can never shift the remaining pairs onto the wrong answer.
    """
    by_id = _scores_by_answer_id(per_answer_scores, valid_answer_ids)
    pairs = []
    for answer_id, rating in ratings:
        e = by_id.get(_coerce_int(answer_id))
        if e is None:
            continue
        if e.get("substantive", True) is False:
            continue
        pairs.append((rating, e.get("score")))
    return pairs


def substantive_stages(per_answer_scores: list, valid_answer_ids=None) -> set:
    """INT-11: the set of stage names (e.g. {"DOMAIN", "CASE"}) that have at least
    one substantive answer, determined by the answer_id join. Used to gate round
    bands so a round in which every answer was a non-answer can't show a positive band.
    """
    by_id = _scores_by_answer_id(per_answer_scores, valid_answer_ids)
    out = set()
    for e in by_id.values():
        if e.get("substantive", True) is False:
            continue
        stage = str(e.get("stage", "")).strip().upper()
        if stage:
            out.add(stage)
    return out


def gate_round_scores(round_scores: dict, sub_stages: set) -> dict:
    """INT-11: zero any *scored* round (warmup/domain/behavioural/case) that the join
    says has no substantive answers, so band math never rewards a round of pure
    non-answers. REVERSE (and any non-answer round) is left untouched — it has no
    per-answer scores to join against and is scored separately.
    """
    scored_round_to_stage = {
        "warmup": "WARMUP", "domain": "DOMAIN",
        "behavioural": "BEHAVIOURAL", "case": "CASE",
    }
    if not isinstance(round_scores, dict):
        return {}
    out = {}
    for key, val in round_scores.items():
        stage = scored_round_to_stage.get(str(key).strip().lower())
        if stage is not None and stage not in sub_stages:
            out[key] = 0
        else:
            out[key] = val
    return out


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
