"""Context-weighted scoring — the benchmark, the band gates, and the evidence floor.

Pure logic only (no DB, no I/O), like stages.py and presence.py. Consumed by main.py.

THE PROBLEM THIS FIXES
Easy / 10 minutes / raw 100 used to read stronger than Critical / 45 minutes / raw 75.
That is exactly backwards, and it is the one thing a readiness product cannot get wrong:
a score with no context attached is not a score, it is a compliment. A perfect run at a
lower bar is a perfect run at a lower bar, and the readout has to say so.

THE TWO NUMBERS, AND WHY THERE ARE TWO
  raw       — the level-anchored rubric score the debrief model produced. It answers
              "how good were these answers, for someone at this level?" and NOTHING else.
              It is never re-weighted, and a skipped round never drags it down: skipped
              is not failed, and that promise lives on the raw number.
  benchmark — raw, weighted by the context they chose to be tested in. It answers the
              only question a placement cell actually asks: "against a real bar, where
              is this person?" This is the number history trends and NudgeAI reads.

Level is deliberately NOT a benchmark factor. The raw rubric is already anchored to the
candidate's level (a fresher is scored as a fresher), so weighting by level again would
count the same fact twice. Difficulty, duration, feedback style and coverage are all
things the candidate CHOSE about the bar; level is who they are. Only the first kind is
a multiplier here.

BANDS OUTRANK ARITHMETIC
The band is earned from the RAW score (the rubric's verdict on the answers) and then
GATED by context. A gate can only ever cap a band DOWNWARD — no factor in this file can
promote anyone. That asymmetry is on purpose: it is the difference between "we could not
see enough to call you ready" and "we have decided you are not".
"""

# ── THE ONE TUNABLE TABLE ────────────────────────────────────────────────────
# Every constant that shapes a benchmark lives HERE and nowhere else. Tuning is editing
# this dict and bumping WEIGHTS_VERSION — nothing else in the codebase holds a weight.
#
# Bump WEIGHTS_VERSION on ANY change to the numbers below. Stored attempts keep their own
# version and their own stored benchmark, so a tuning never rewrites history — see
# "PERSIST, NEVER RECOMPUTE" in main.end_session. The version is the audit trail that lets
# a 42 from July and a 42 from September be compared honestly, or knowingly not compared.
# 2026.07-2 — the Intake sprint shipped the mode selector, so MODE_FACTOR_ACTIVE flipped
# to True and the reserved rows below started counting. Only TEXT actually moves a number
# (×0.90); AUDIO and VIDEO are 1.00, so every session that existed before this bump scores
# exactly as it did. The version still bumps: what a benchmark MEANS changed, and a
# benchmark whose meaning changed silently is the thing this field exists to prevent.
WEIGHTS_VERSION = "2026.07-2"

WEIGHTS = {
    # What they chose to be tested at. An Easy panel is a lower bar; the same answers
    # cannot mean the same thing against it.
    "difficulty": {
        "Easy": 0.60,
        "Realistic": 1.00,
        "Stretch": 1.15,
        "Critical": 1.25,
    },
    # How much evidence the session could physically produce. Ten minutes is a taste:
    # not a judgement on them, a statement about how little we saw. Keyed by the PLANNED
    # duration in minutes; see evidence_factor for durations between the buckets.
    "evidence": {
        10: 0.70,
        20: 1.00,
        30: 1.10,
        45: 1.20,
    },
    # Coach mode feeds back after every answer — the later answers are helped, and an
    # honest benchmark says so. It is still a good way to practise; it is just not a
    # simulation of a room where nobody coaches you.
    "feedback": {
        "interview": 1.00,
        "coach": 0.90,
    },
    # HOW THEY ANSWERED. Live as of the Intake sprint — the selector exists, so a mode is
    # now a thing a student CHOSE rather than a row nobody could reach.
    #
    # TEXT is 0.90 because a typed answer is an easier artefact than a spoken one: you can
    # edit it, reorder it, and take the pause back. The content is scored identically
    # (typed = spoken for content — see B2), and the readout NEVER fabricates a voice
    # Delivery metric for a session that had no voice. The 0.90 is about the bar the
    # answer cleared, not a penalty for typing.
    #
    # AUDIO and VIDEO are both 1.00: VIDEO adds a camera, not a harder question. Presence
    # is report-only and never enters a benchmark, so there is no third number here.
    #
    # This dict is the ONLY home for these. Do not add a second mode weight anywhere (B4).
    "mode": {
        "TEXT": 0.90,
        "AUDIO": 1.00,
        "VIDEO": 1.00,
    },
}

# Flipped by the Intake sprint, which is the sprint that made a mode choosable. The rule
# it was guarding still stands: nothing may be weighted by a mode nobody can choose.
MODE_FACTOR_ACTIVE = True

# The phase doc's older vocabulary. TEXT/VOICE/HYBRID was reconciled to TEXT/AUDIO/VIDEO
# by the Intake sprint (SCORING_CONTEXT left that call to it, deliberately). These stay so
# that a stored row, an older client or a half-applied deploy resolves instead of silently
# scoring 1.00 for an unrecognised name. intake.MODE_ALIASES mirrors this for the UI half.
MODE_ALIASES = {"VOICE": "AUDIO", "HYBRID": "VIDEO"}

# The benchmark a learner SEES is capped at 100 — "127" is not a readiness statement, it
# is a bug report. The uncapped value is still stored: it is the only way to tell a
# scraped-past-100 run from a comfortable one when these weights are next tuned.
BENCHMARK_DISPLAY_CAP = 100

# ── The evidence floor ───────────────────────────────────────────────────────
# Under three substantive answers there is no readout to write. Not a bad one — none.
# Two answers cannot separate a strong candidate from a lucky one, and a band printed on
# that little evidence is a guess wearing a verdict's clothes.
MIN_SUBSTANTIVE_ANSWERS = 3

# The rounds coverage is measured over: the scored ones. REVERSE (their questions for us)
# is not a scored round and never counts toward coverage.
COVERAGE_ROUNDS = ("WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE")

ROUND_LABELS = {
    "WARMUP": "Warm-up",
    "DOMAIN": "Domain",
    "BEHAVIOURAL": "Behavioural",
    "CASE": "Case",
}

# Weakest to strongest. The ONE ordering of the bands, so "one band below" and "cap at"
# mean the same thing everywhere.
BAND_LADDER = ("Not Ready", "Building", "Interview-Ready", "Offer-Ready")


def _band_rank(band: str) -> int:
    try:
        return BAND_LADDER.index(band)
    except ValueError:
        return 0


def _num(v, default=None):
    """Best-effort float. Returns `default` on anything that is not a number."""
    if isinstance(v, bool):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── The factors ──────────────────────────────────────────────────────────────

def difficulty_factor(difficulty: str) -> float:
    """Unknown difficulty -> 1.00. A typo must never silently deflate someone's score."""
    return WEIGHTS["difficulty"].get(str(difficulty or "").strip().title(), 1.00)


def evidence_factor(duration_min) -> float:
    """The weight for a PLANNED session length.

    The table has four buckets (10/20/30/45) but the API accepts 5-60, so a duration
    between buckets takes the weight of the highest bucket it has actually reached —
    a 25-minute session is a 20-minute session's worth of evidence, not a 30's. Below
    the smallest bucket it takes that bucket's weight (there is no fifth rung below 10,
    and inventing one here would put a weight outside the table).
    """
    d = _num(duration_min)
    if d is None:
        return 1.00
    buckets = sorted(WEIGHTS["evidence"])
    weight = WEIGHTS["evidence"][buckets[0]]
    for b in buckets:
        if d >= b:
            weight = WEIGHTS["evidence"][b]
    return weight


def feedback_factor(feedback: str) -> float:
    """`feedback` is the session's `mode` column — interview | coach. (The lobby renames
    the heading to FEEDBACK; the column keeps its name, and this is where the two meet.)"""
    return WEIGHTS["feedback"].get(str(feedback or "").strip().lower(), 1.00)


def mode_factor(mode: str = None) -> float:
    """How they answered → the factor it earns. TEXT 0.90, AUDIO/VIDEO 1.00.

    LIVE since the Intake sprint (WEIGHTS_VERSION 2026.07-2).

    An UNKNOWN or missing mode returns 1.00, never 0.90. That asymmetry is deliberate: a
    session on a database without migration 009 has no stored mode, and guessing TEXT there
    would quietly mark a spoken session down for a column that simply is not there. When we
    do not know, we do not charge for it.
    """
    if not MODE_FACTOR_ACTIVE:
        return 1.00
    key = str(mode or "").strip().upper()
    key = MODE_ALIASES.get(key, key)
    return WEIGHTS["mode"].get(key, 1.00)


def coverage_factor(rounds_attempted, rounds_offered) -> float:
    """attempted / offered, clamped to [0, 1].

    This TEMPERS THE BENCHMARK ONLY. It never touches raw, and it is not a penalty for
    skipping: skipped ≠ failed is a promise made on the raw score, and it still holds.
    What this says is narrower and true — we saw two rounds of four, so we are two
    rounds short of a claim about how ready they are.
    """
    offered = _num(rounds_offered, 0) or 0
    if offered <= 0:
        return 1.00
    attempted = max(0.0, _num(rounds_attempted, 0) or 0)
    return max(0.0, min(1.0, attempted / offered))


def coverage(sub_stages) -> dict:
    """Which scored rounds had a substantive answer, and which did not.

    `sub_stages` is stages.substantive_stages(...) — the set of stages the answer-id join
    says were genuinely attempted.
    """
    seen = {str(s).strip().upper() for s in (sub_stages or set())}
    covered = [r for r in COVERAGE_ROUNDS if r in seen]
    skipped = [r for r in COVERAGE_ROUNDS if r not in seen]
    return {
        "covered": covered,
        "skipped": skipped,
        "covered_labels": [ROUND_LABELS[r] for r in covered],
        "skipped_labels": [ROUND_LABELS[r] for r in skipped],
        "attempted": len(covered),
        "offered": len(COVERAGE_ROUNDS),
    }


# ── The benchmark ────────────────────────────────────────────────────────────

def compute_benchmark(
    raw,
    *,
    difficulty: str,
    duration_min,
    feedback: str,
    rounds_attempted,
    rounds_offered,
    mode: str = None,
) -> dict:
    """benchmark = raw × difficulty × evidence × feedback × coverage (× mode, when it wakes).

    Returns everything needed to persist the attempt AND to explain it, because those are
    the same thing: a score you cannot reproduce from what you stored is a score you
    cannot defend when a student asks.
    """
    r = _num(raw, 0) or 0.0
    factors = {
        "difficulty": difficulty_factor(difficulty),
        "evidence": evidence_factor(duration_min),
        "feedback": feedback_factor(feedback),
        "coverage": coverage_factor(rounds_attempted, rounds_offered),
        "mode": mode_factor(mode),
    }
    uncapped = r
    for f in factors.values():
        uncapped *= f

    return {
        "raw": int(round(r)),
        "benchmark": int(min(BENCHMARK_DISPLAY_CAP, round(uncapped))),
        "benchmark_uncapped": round(uncapped, 1),
        "factors": {k: round(v, 4) for k, v in factors.items()},
        "inputs": {
            "difficulty": difficulty,
            "duration_min": int(_num(duration_min, 0) or 0),
            "feedback": feedback,
            "mode": mode,
            "rounds_attempted": int(_num(rounds_attempted, 0) or 0),
            "rounds_offered": int(_num(rounds_offered, 0) or 0),
        },
        "weights_version": WEIGHTS_VERSION,
    }


# ── The band gates ───────────────────────────────────────────────────────────
# Each gate returns the HIGHEST band this context can support, or None when it has no
# opinion. They can only cap downward — see the module docstring.

EASY_BAND_CAP = "Building"
SHORT_SESSION_MINUTES = 10
OFFER_READY_MIN_MINUTES = 20
OFFER_READY_DIFFICULTIES = ("Stretch", "Critical")


def _easy_gate(difficulty: str) -> str | None:
    return EASY_BAND_CAP if str(difficulty or "").strip().title() == "Easy" else None


def _short_session_gate(duration_min, earned: str) -> str | None:
    """A 10-minute session caps ONE BAND BELOW whatever the answers earned.

    Not because the answers were worse — because ten minutes cannot show us enough to
    stand behind the band they'd otherwise get. The cap is relative to what they earned,
    so it reads as "we didn't see enough", never as "you did badly".
    """
    d = _num(duration_min)
    if d is None or d > SHORT_SESSION_MINUTES:
        return None
    return BAND_LADDER[max(0, _band_rank(earned) - 1)]


def _offer_ready_gate(difficulty: str, duration_min, case_attempted: bool) -> str | None:
    """Offer-Ready is a claim about a real hiring bar, so it is only ever awarded where
    one was actually simulated: Stretch or Critical, 20 minutes or more, case attempted.
    Miss any of the three and the ceiling is Interview-Ready."""
    d = _num(duration_min, 0) or 0
    ok = (
        str(difficulty or "").strip().title() in OFFER_READY_DIFFICULTIES
        and d >= OFFER_READY_MIN_MINUTES
        and bool(case_attempted)
    )
    return None if ok else "Interview-Ready"


def _offer_ready_missing(difficulty: str, duration_min, case_attempted: bool) -> list[str]:
    """The plain-words list of what an Offer-Ready run was missing."""
    d = _num(duration_min, 0) or 0
    missing = []
    if str(difficulty or "").strip().title() not in OFFER_READY_DIFFICULTIES:
        missing.append("it needs Stretch or Critical")
    if d < OFFER_READY_MIN_MINUTES:
        missing.append("it needs 20 minutes or more")
    if not case_attempted:
        missing.append("it needs the case round attempted")
    return missing


def band_gates(earned: str, *, difficulty: str, duration_min, case_attempted: bool, raw=None) -> dict:
    """Apply every gate to the band the answers EARNED. Returns the final band, the gates
    that bound, and the ladder copy that tells them how to unlock the next one.

    The copy is the point. A cap with no explanation is just a number that feels unfair;
    a cap that says "Easy caps at Building — step up to Realistic to unlock
    Interview-Ready" is a next session.
    """
    earned = earned if earned in BAND_LADDER else "Not Ready"

    # (code, cap, priority) — priority breaks ties so the copy is deterministic.
    candidates = [
        ("easy", _easy_gate(difficulty)),
        ("short_session", _short_session_gate(duration_min, earned)),
        ("offer_ready", _offer_ready_gate(difficulty, duration_min, case_attempted)),
    ]

    final = earned
    bound = []
    for code, cap in candidates:
        if cap is None or _band_rank(cap) >= _band_rank(earned):
            continue  # no opinion, or an opinion that isn't binding on this run
        bound.append((code, cap))
        if _band_rank(cap) < _band_rank(final):
            final = cap

    gates = [
        {"code": code, "cap": cap, "copy": _gate_copy(code, earned, cap, difficulty, duration_min, case_attempted, raw)}
        for code, cap in bound
    ]

    return {
        "band": final,
        "earned_band": earned,
        "capped": final != earned,
        # The binding gate — the one that actually set the ceiling. This is the line the
        # readout leads with; the rest of `gates` is the ladder underneath it.
        "copy": next((g["copy"] for g in gates if g["cap"] == final), ""),
        "gates": gates,
    }


def _next_band(band: str) -> str:
    return BAND_LADDER[min(len(BAND_LADDER) - 1, _band_rank(band) + 1)]


def _gate_copy(code, earned, cap, difficulty, duration_min, case_attempted, raw) -> str:
    if code == "easy":
        r = _num(raw)
        opener = "Perfect run" if (r is not None and r >= 95) else "Strong run"
        return (
            f"{opener} — Easy caps at {EASY_BAND_CAP}. Step up to Realistic to unlock "
            f"{_next_band(EASY_BAND_CAP)}."
        )
    if code == "short_session":
        return (
            f"Ten minutes is a taste, not an interview — it caps you one band below the "
            f"{earned} your answers earned. Give it 20 minutes and the band is scored at "
            f"full strength."
        )
    if code == "offer_ready":
        missing = _offer_ready_missing(difficulty, duration_min, case_attempted)
        return (
            "Your answers earned Offer-Ready, and Offer-Ready is only awarded where a real "
            "hiring bar was simulated: " + _join_plainly(missing) + "."
        )
    return ""


def _join_plainly(items: list[str]) -> str:
    """['a', 'b', 'c'] -> 'a, b and c'. One place, so no readout ever ships an 'a, b, '."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


# ── The evidence floor ───────────────────────────────────────────────────────

def has_minimum_evidence(substantive_answers) -> bool:
    """Three substantive answers, or there is no verdict to give.

    An auto-submitted partial IS an answer — they were speaking, we cut them off, and what
    they said counts. An empty skip is not: nothing was said, so there is nothing to score.
    Both of those calls are made upstream by stages.is_non_substantive; this only counts.
    """
    return int(_num(substantive_answers, 0) or 0) >= MIN_SUBSTANTIVE_ANSWERS


INSUFFICIENT_EVIDENCE_COPY = (
    "There isn't enough here to score. You gave {n} substantive answer{s}, and a readiness "
    "band needs at least {min}. That is a statement about the evidence, not about you — "
    "nothing has been marked against you, and the next attempt starts clean."
)


def insufficient_evidence_card(substantive_answers) -> dict:
    n = int(_num(substantive_answers, 0) or 0)
    return {
        "substantive_answers": n,
        "minimum": MIN_SUBSTANTIVE_ANSWERS,
        "copy": INSUFFICIENT_EVIDENCE_COPY.format(
            n=n, s="" if n == 1 else "s", min=MIN_SUBSTANTIVE_ANSWERS
        ),
    }


# ── Show the math ────────────────────────────────────────────────────────────
# The expandable "How this score is calculated". Plain words, this attempt's real numbers.
# A student who cannot see why 100 became 42 has been told they are worse than they are.

_FACTOR_COPY = {
    "difficulty": "You chose {difficulty}. {why}",
    "evidence": "A {duration}-minute session. {why}",
    "feedback": "{label}. {why}",
    "coverage": "You reached {attempted} of {offered} scored rounds. {why}",
    "mode": "Session mode. {why}",
}

_DIFFICULTY_WHY = {
    "Easy": "A warm-up pace is a lower bar than a real panel, so the same answers count for less here.",
    "Realistic": "This is the real bar, so your answers count exactly as they are.",
    "Stretch": "A tougher panel than the real bar, so your answers count for more.",
    "Critical": "The pressure panel is the highest bar we simulate, so your answers count for the most.",
}


def math_lines(result: dict, band_result: dict = None) -> list[dict]:
    """The rows of "How this score is calculated", in the order they multiply.

    `result` is compute_benchmark's return. Reads from the STORED factors, never from the
    live table — an old attempt explains itself with the weights it was actually scored on.
    """
    result = result or {}
    factors = result.get("factors", {}) or {}
    inputs = result.get("inputs", {}) or {}
    difficulty = str(inputs.get("difficulty") or "").strip().title()
    feedback = str(inputs.get("feedback") or "").strip().lower()
    duration = inputs.get("duration_min")

    rows = [{
        "key": "raw",
        "label": "Your answers, scored for your level",
        "value": f"{result.get('raw', 0)}",
        "note": "The rubric verdict on what you actually said. Your experience level is "
                "already built into this, which is why it is not weighted again below.",
    }]

    def row(key, label, value, note):
        rows.append({"key": key, "label": label, "value": value, "note": note})

    if "difficulty" in factors:
        row("difficulty", f"Difficulty — {difficulty or 'Unknown'}",
            f"×{factors['difficulty']:.2f}",
            _DIFFICULTY_WHY.get(difficulty, "Weighted for the bar you chose."))
    if "evidence" in factors:
        row("evidence", f"Evidence — {duration} min",
            f"×{factors['evidence']:.2f}",
            "A longer session shows more, so it can support a stronger claim. This is about "
            "how much we saw, not how well you did.")
    if "feedback" in factors:
        label = "Coach — feedback after every answer" if feedback == "coach" else "Interview — feedback at the end"
        why = ("Coaching mid-session helps the answers that follow, so a benchmark counts it slightly lower."
               if feedback == "coach" else
               "No help mid-session, exactly like a real room.")
        row("feedback", f"Feedback style — {label}", f"×{factors['feedback']:.2f}", why)
    if "coverage" in factors:
        # The note has to match what actually happened. "Rounds you didn't reach" printed
        # under "4 of 4 rounds" is the kind of small lie that makes a learner distrust
        # every other number on the page.
        why = (
            "You reached every scored round, so nothing is held back here."
            if factors["coverage"] >= 1.0 else
            "Rounds you didn't reach aren't marked against your answers — they only mean we "
            "saw less of you, so the benchmark claims less."
        )
        row("coverage",
            f"Coverage — {inputs.get('rounds_attempted', 0)} of {inputs.get('rounds_offered', 0)} rounds",
            f"×{factors['coverage']:.2f}", why)
    # Only when we actually know how they answered. A session scored on a database without
    # migration 009 has no mode, and "Mode — Unknown ×1.00" is a row that explains nothing
    # while implying we measured something. No row is the honest rendering of no data.
    if MODE_FACTOR_ACTIVE and "mode" in factors and inputs.get("mode"):
        mode_label = str(inputs["mode"]).upper()
        mode_label = MODE_ALIASES.get(mode_label, mode_label)
        row("mode", f"Mode — {mode_label.title()}", f"×{factors['mode']:.2f}",
            "Typed answers are scored on the same content bar; the weight reflects the "
            "one you chose."
            if mode_label == "TEXT" else
            "Speaking is the full bar — no adjustment.")

    uncapped = result.get("benchmark_uncapped")
    benchmark = result.get("benchmark")
    if uncapped is not None and benchmark is not None and uncapped > benchmark:
        row("cap", "Benchmark", f"{benchmark}",
            f"The maths came to {uncapped:g}. 100 is the top of the scale — you cleared it "
            f"with room to spare.")
    else:
        row("total", "Benchmark", f"{benchmark}", "Your answers, weighted for the bar you chose.")

    for g in (band_result or {}).get("gates", []) or []:
        row(f"gate:{g['code']}", "Band gate", g["cap"], g["copy"])

    return rows


# ── The re-attempt window ────────────────────────────────────────────────────
# When to come back. Deterministic from the band, because the honest answer depends on how
# much work is between them and the next rung — not on how they feel about the score.

_REATTEMPT = {
    "Offer-Ready": (7, "You're at the bar. Book the next one inside a week — this is a skill "
                       "that goes cold, and the only thing left to do is keep it warm."),
    "Interview-Ready": (3, "Work the first three days of the plan, then go again. You're close "
                           "enough that the gap is reps, not study."),
    "Building": (7, "Give the 7-day plan a full week before you re-attempt. Going again tomorrow "
                    "just re-runs the same interview."),
    "Not Ready": (7, "Take the full week on the plan, then come back. There is real work between "
                     "here and the next band, and a week of it changes the session."),
}


def reattempt_window(band: str) -> dict:
    """{days, copy} — a stable shape. NudgeAI schedules off `days`; the readout prints `copy`."""
    days, copy = _REATTEMPT.get(band, _REATTEMPT["Not Ready"])
    return {"days": days, "copy": copy}


# ── The EcoPro hook ──────────────────────────────────────────────────────────

def ecopro_export(*, band, benchmark, gaps, reattempt, session_id=None, scored=True) -> dict:
    """What session close hands to the rest of the EcoPro agents.

    STABLE SHAPE — NudgeAI reads it today, CareerIQ will read it later. Add keys freely;
    do not rename or remove one without checking who is reading it.

    Deliberately excluded: presence, calibration and focus events. They are report-only —
    they never entered the benchmark, and they must not leak into a downstream agent as if
    they had. An agent that schedules study time off a camera signal is exactly the product
    this is not.
    """
    top = []
    for g in (gaps or [])[:3]:
        if isinstance(g, dict):
            top.append({
                "fix": g.get("gap", ""),
                "try_this_next_time": g.get("tryThisNextTime", ""),
                "course": g.get("upskillizeCourse", ""),
            })
        elif isinstance(g, str):
            top.append({"fix": g, "try_this_next_time": "", "course": ""})
    return {
        "session_id": session_id,
        "scored": bool(scored),
        "band": band if scored else None,
        "benchmark": benchmark if scored else None,
        "top_fixes": top,
        "reattempt_window": reattempt or {},
        "weights_version": WEIGHTS_VERSION,
    }


# ── The trend (history) ──────────────────────────────────────────────────────

PLACEMENT_WINDOW = 3


def latest_average(benchmarks: list, window: int = PLACEMENT_WINDOW):
    """The average of the latest `window` benchmarks — NEWEST FIRST.

    Any placement-facing view reads THIS, never the best-ever. A best-ever score is a
    story about one good day; a TPO deciding who walks into a drive needs to know where
    this person is now. Returns None when there is nothing scored to average.
    """
    vals = [v for v in (_num(b) for b in (benchmarks or [])) if v is not None]
    if not vals:
        return None
    window = max(1, int(window or 1))
    take = vals[:window]
    return round(sum(take) / len(take), 1)
