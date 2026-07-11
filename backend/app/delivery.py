"""InterviewIQ delivery metrics (Voice Phase 3 — how an answer was *delivered*).

Pure logic only (no I/O, no vendor calls) so it is trivially testable, mirroring
stages.py. Consumed by main.py at STT time (per spoken answer) and at debrief time
(aggregated into the readout's Delivery Profile).

Privacy: these are DERIVED METRICS over a transcript + a duration + optional vendor
timestamps. No audio is involved here — the recording was already transcribed and
discarded upstream. Metrics are not a recording (see VOICE_PHASE3_REPORT.md §privacy).

Scoring note: the 0-100 delivery score below is a TRANSPARENT v1 heuristic, not a
calibrated model — it is flagged for product/legal sign-off in the report §6 and does
NOT affect the overall readiness band (delivery is informational in v1).
"""

import re

from .stages import band_for

# Pace bands (words per minute). Sweet spot is a natural, measured interview pace.
PACE_SWEET_LOW = 130
PACE_SWEET_HIGH = 160
PACE_SLOW = 110      # < this reads as hesitant/under-prepared
PACE_RUSHED = 180    # > this reads as nervous/gabbling

# Filler tokens (single words + phrases). Hinglish included: matlab, woh.
FILLERS = ["um", "uh", "like", "basically", "actually", "you know", "matlab", "woh"]

# A gap this long BETWEEN spoken segments reads as a stall. The pre-answer thinking
# pause (before the first word) is fine and is naturally excluded — we only look at
# gaps between consecutive segments.
PAUSE_THRESHOLD_SECONDS = 2.0

_FILLER_RX = {f: re.compile(r"\b" + re.escape(f) + r"\b", re.IGNORECASE) for f in FILLERS}


def count_words(transcript: str) -> int:
    return len((transcript or "").split())


def count_fillers(transcript: str) -> tuple[int, dict]:
    """Return (total_fillers, {filler: count}) for fillers that actually occurred."""
    per = {}
    total = 0
    text = transcript or ""
    for f, rx in _FILLER_RX.items():
        n = len(rx.findall(text))
        if n:
            per[f] = n
            total += n
    return total, per


def pace_label(wpm) -> str | None:
    if wpm is None:
        return None
    if wpm < PACE_SLOW:
        return "slow"
    if wpm > PACE_RUSHED:
        return "rushed"
    return "on_pace"


def long_pauses(timestamps) -> int | None:
    """Count gaps > PAUSE_THRESHOLD between consecutive spoken segments.

    Saarika returns parallel arrays {words, start_time_seconds, end_time_seconds}.
    Returns None when there is no usable multi-segment timing (e.g. the model
    returned the whole utterance as one segment) so the caller shows "no pause data"
    rather than a misleading zero.
    """
    if not isinstance(timestamps, dict):
        return None
    starts = timestamps.get("start_time_seconds")
    ends = timestamps.get("end_time_seconds")
    if not isinstance(starts, list) or not isinstance(ends, list):
        return None
    n = min(len(starts), len(ends))
    if n < 2:
        return None
    count = 0
    for i in range(n - 1):
        try:
            gap = float(starts[i + 1]) - float(ends[i])
        except (TypeError, ValueError):
            continue
        if gap > PAUSE_THRESHOLD_SECONDS:
            count += 1
    return count


def compute(transcript: str, duration_seconds, timestamps=None, confidence=None) -> dict | None:
    """Metrics for ONE spoken answer, or None if there's no transcript to measure.

    Never raises — a bad duration just yields wpm=None; missing timestamps yield
    long_pause_count=None. All fields degrade independently and gracefully.
    """
    if not transcript or not transcript.strip():
        return None

    words = count_words(transcript)

    try:
        dur = float(duration_seconds)
    except (TypeError, ValueError):
        dur = 0.0
    wpm = None
    filler_per_min = None
    total_fillers, per_filler = count_fillers(transcript)
    if dur > 0:
        minutes = dur / 60.0
        wpm = round(words / minutes)
        filler_per_min = round(total_fillers / minutes, 1)

    articulation = None
    if isinstance(confidence, (int, float)):
        articulation = round(float(confidence), 3)

    return {
        "word_count": words,
        "duration_seconds": round(dur, 1) if dur > 0 else None,
        "wpm": wpm,
        "pace": pace_label(wpm),
        "filler_count": total_fillers,
        "filler_per_min": filler_per_min,
        "fillers": per_filler,
        "long_pause_count": long_pauses(timestamps),
        "articulation": articulation,
    }


def sanitize(metrics) -> dict | None:
    """Re-validate a client-echoed metrics dict before it is persisted.

    The frontend echoes the /session/stt metrics back on /session/turn, so treat the
    payload as untrusted: keep ONLY known keys with the expected types, drop the rest.
    Returns a clean dict, or None if there's nothing usable. (Metrics are
    informational and never affect the readiness band, so this is belt-and-suspenders,
    not a security boundary — but it keeps junk out of the DB and the readout.)
    """
    if not isinstance(metrics, dict):
        return None
    out = {}
    for key in ("word_count", "filler_count"):
        v = metrics.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            out[key] = v
    for key in ("wpm", "duration_seconds", "filler_per_min", "articulation"):
        v = metrics.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = v
    pace = metrics.get("pace")
    if pace in ("slow", "on_pace", "rushed"):
        out["pace"] = pace
    lpc = metrics.get("long_pause_count")
    if isinstance(lpc, int) and not isinstance(lpc, bool):
        out["long_pause_count"] = lpc
    fillers = metrics.get("fillers")
    if isinstance(fillers, dict):
        clean = {k: v for k, v in fillers.items()
                 if k in FILLERS and isinstance(v, int) and not isinstance(v, bool) and v > 0}
        if clean:
            out["fillers"] = clean
    return out or None


# ── Aggregation for the readout Delivery Profile (Part D) ────────────────────

MIN_SPOKEN_FOR_BAND = 3


def _pace_verdict(avg_wpm) -> str:
    if avg_wpm is None:
        return "No pace data yet."
    if avg_wpm < PACE_SLOW:
        return f"{avg_wpm} wpm — a little slow; aim for {PACE_SWEET_LOW}–{PACE_SWEET_HIGH}."
    if avg_wpm > PACE_RUSHED:
        return f"{avg_wpm} wpm — rushed; slow down toward {PACE_SWEET_LOW}–{PACE_SWEET_HIGH}."
    if PACE_SWEET_LOW <= avg_wpm <= PACE_SWEET_HIGH:
        return f"{avg_wpm} wpm — right in the {PACE_SWEET_LOW}–{PACE_SWEET_HIGH} sweet spot."
    return f"{avg_wpm} wpm — close to the {PACE_SWEET_LOW}–{PACE_SWEET_HIGH} sweet spot."


def _delivery_score(avg_wpm, filler_per_min, avg_pauses) -> int:
    """TRANSPARENT v1 heuristic (0-100). Provisional — see report §6."""
    score = 100
    if avg_wpm is not None:
        if PACE_SWEET_LOW <= avg_wpm <= PACE_SWEET_HIGH:
            pass
        elif avg_wpm < PACE_SLOW or avg_wpm > PACE_RUSHED:
            score -= 25
        else:
            score -= 10
    if filler_per_min is not None:
        if filler_per_min <= 2:
            pass
        elif filler_per_min <= 5:
            score -= 10
        elif filler_per_min <= 8:
            score -= 20
        else:
            score -= 30
    if avg_pauses is not None:
        score -= min(int(round(avg_pauses)) * 5, 20)
    return max(0, min(100, score))


def aggregate(metrics_list: list) -> dict:
    """Roll per-answer metrics into the readout Delivery Profile.

    Fewer than MIN_SPOKEN_FOR_BAND spoken answers → no band, a nudge to speak more.
    """
    spoken = [m for m in (metrics_list or []) if isinstance(m, dict)]
    n = len(spoken)
    if n < MIN_SPOKEN_FOR_BAND:
        return {
            "spoken_answers": n,
            "enough_data": False,
            "message": "Not enough voice data — try answering aloud next session.",
        }

    wpms = [m["wpm"] for m in spoken if isinstance(m.get("wpm"), (int, float))]
    avg_wpm = round(sum(wpms) / len(wpms)) if wpms else None

    fpms = [m["filler_per_min"] for m in spoken if isinstance(m.get("filler_per_min"), (int, float))]
    avg_fpm = round(sum(fpms) / len(fpms), 1) if fpms else None

    total_fillers = {}
    for m in spoken:
        for f, c in (m.get("fillers") or {}).items():
            total_fillers[f] = total_fillers.get(f, 0) + c
    top_fillers = sorted(total_fillers.items(), key=lambda kv: (-kv[1], kv[0]))[:2]

    pause_counts = [m["long_pause_count"] for m in spoken if isinstance(m.get("long_pause_count"), int)]
    avg_pauses = (sum(pause_counts) / len(pause_counts)) if pause_counts else None
    if avg_pauses is None:
        pause_note = "Pause timing wasn't available for these answers."
    elif avg_pauses < 0.5:
        pause_note = "Good flow — few long mid-answer pauses."
    else:
        pause_note = f"Noticeable mid-answer pauses (~{round(avg_pauses, 1)} per answer > 2s) — practise bridging phrases."

    if top_fillers:
        named = ", ".join(f'"{f}" ×{c}' for f, c in top_fillers)
        filler_note = (
            f"{avg_fpm} fillers/min. Top offenders: {named}."
            if avg_fpm is not None else f"Top filler words: {named}."
        )
    else:
        filler_note = "Very few filler words — crisp delivery."

    score = _delivery_score(avg_wpm, avg_fpm, avg_pauses)
    return {
        "spoken_answers": n,
        "enough_data": True,
        "avg_wpm": avg_wpm,
        "pace_verdict": _pace_verdict(avg_wpm),
        "filler_per_min": avg_fpm,
        "top_fillers": top_fillers,
        "filler_note": filler_note,
        "pause_note": pause_note,
        "delivery_score": score,
        "delivery_band": band_for(score),
        "note": "Shown separately, not counted in your readiness band yet.",
    }
