"""InterviewIQ focus / presence engine — pure logic (Interview Room, Phase C/E).

PRIVACY (the whole point):
  Camera frames NEVER leave the browser. This module never sees an image, a video
  frame, or a facial landmark — only EVENT STRINGS and TIMESTAMPS that the client
  derived on-device. There is deliberately no code path here that could accept media.

HONESTY (hold this line in review):
  We measure OBSERVABLE BEHAVIOUR (did a face stay in frame, did the tab stay
  focused), never emotion, sentiment, seriousness, or personality. No emotion words
  appear in any label, prompt, or readout string produced here.

FAIRNESS:
  * The camera signals are heuristic and NOISY. The user-facing vocabulary is
    "attention" and "presence" — the word "cheating" appears nowhere, by design.
  * A learner who JOINS camera-off (an accessibility path) has the camera signals
    disabled entirely and gets NO camera-based presence lines in the readout. They
    are never penalised for it. tab/window signals still apply — they need no camera.
"""

# ── The closed set of signals ────────────────────────────────────────────────
# Attention signals (Phase C).
CAMERA_SIGNALS = frozenset({"no_face", "multiple_faces", "looking_away"})
# These need no camera at all, so they work on every join path.
NON_CAMERA_SIGNALS = frozenset({"tab_hidden", "window_blur"})
ATTENTION_SIGNALS = CAMERA_SIGNALS | NON_CAMERA_SIGNALS
# Device-commitment signals (Phase E). Recorded in the same table so the ladder is
# persisted and a refresh cannot dodge it.
DEVICE_SIGNALS = frozenset({"camera_off", "mic_off"})

FOCUS_EVENT_TYPES = ATTENTION_SIGNALS | DEVICE_SIGNALS

# One event per signal per this window. The client debounces too; the server is the
# authority (a hostile or buggy client cannot spam the ladder).
DEBOUNCE_SECONDS = 30


def is_valid_event(event_type: str) -> bool:
    return event_type in FOCUS_EVENT_TYPES


def is_camera_signal(event_type: str) -> bool:
    return event_type in CAMERA_SIGNALS


def accepts_event(event_type: str, camera_at_join: bool) -> bool:
    """Camera signals are ignored outright when the learner joined camera-off."""
    if not is_valid_event(event_type):
        return False
    if is_camera_signal(event_type) and not camera_at_join:
        return False
    return True


def within_debounce(seconds_since_last, window: int = DEBOUNCE_SECONDS) -> bool:
    """True when an identical signal arrived too recently and must be dropped."""
    if seconds_since_last is None:
        return False
    try:
        return float(seconds_since_last) < window
    except (TypeError, ValueError):
        return False


# ── Escalation ladder (attention) ────────────────────────────────────────────
# Counts ATTENTION events only — device events run their own ladder below.
def escalation_level(attention_events_total: int) -> int:
    """0 = nothing to say, 1 = gentle, 2 = firm, 3 = will be reflected in feedback."""
    n = max(0, int(attention_events_total or 0))
    if n == 0:
        return 0
    if n <= 2:
        return 1
    if n <= 4:
        return 2
    return 3


def escalation_directive(level: int) -> str:
    """A per-turn instruction telling the interviewer to raise attention ONCE, in
    character. We give INTENT, never a script — the improvised persona (migration 005)
    supplies the words, so the reminder sounds like the same person who has been
    interviewing them. Never punitive, never accusatory, never the word "cheating".
    """
    if level <= 0:
        return ""
    if level == 1:
        return (
            "ATTENTION NOTE (say this ONCE, in your own voice, before your next question): "
            "you have noticed their attention drifting. Add ONE short, calm line asking for "
            "their full attention. Normal tone — no reprimand, no accusation, no drama. "
            "Then carry on with the interview exactly as planned."
        )
    if level == 2:
        return (
            "ATTENTION NOTE (say this ONCE, in your own voice, before your next question): "
            "their attention has drifted repeatedly. Be direct and professional: note that in "
            "a real panel this would cost them, and ask them to stay with you for the "
            "remaining questions. Firm, not harsh. Do NOT accuse them of anything — this is "
            "about presence, not honesty. Then carry on with the interview exactly as planned."
        )
    return (
        "ATTENTION NOTE (say this ONCE, in your own voice, before your next question): "
        "their attention has drifted many times. State plainly and without scolding that you "
        "will reflect this in their feedback, then move on. No sarcasm, no accusations, and "
        "nothing that sounds like a threat. Then carry on with the interview exactly as planned."
    )


# ── Device-commitment ladder (Phase E) ───────────────────────────────────────
# Only ever applies to a learner who JOINED with the camera on. A camera-off join is
# an accessibility path, not a policy breach.
def camera_ladder_action(camera_off_events: int, camera_at_join: bool) -> str:
    """'none' | 'nudge' | 'warn' | 'wrap'."""
    if not camera_at_join:
        return "none"
    n = max(0, int(camera_off_events or 0))
    if n <= 0:
        return "none"
    if n == 1:
        return "nudge"
    if n == 2:
        return "warn"
    return "wrap"


def camera_directive(action: str) -> str:
    if action == "nudge":
        return (
            "CAMERA NOTE (say this ONCE, in your own voice): their camera has gone off. "
            "Ask them, warmly and normally, to turn it back on so you can see them for the "
            "rest of the interview. Then continue as planned."
        )
    if action == "warn":
        return (
            "CAMERA NOTE (say this ONCE, in your own voice): their camera is off again. Say "
            "professionally that you do need the camera on to continue the full interview, "
            "and that if it stays off you will wrap up with what you have covered. No threat, "
            "no scolding. Then continue as planned."
        )
    return ""


# ── The device-policy CLOCKS (the half the ladder was missing) ───────────────
# The ladder above says WHAT happens at each step. These say WHEN a step is reached, so
# a candidate who simply stops responding is not left sitting in a room forever.
#
#   Camera:  each rung of the camera ladder carries a 60s grace. Turn the camera back on
#            inside it and nothing escalates. Let the grace lapse with the camera still
#            off and it counts again — nudge -> warn -> wrap.
#   Silence: if an answer is due and BOTH channels are dead — mic off (or muted) and not
#            one character typed — for 90s, that is abandonment, and we wrap courteously
#            rather than burn their session clock in silence.
#
# Both are enforced client-side (the client owns the wall clock) but DECIDED here, so the
# thresholds are one number in one place and are covered by tests.
CAMERA_GRACE_SECONDS = 60
SILENT_ABANDON_SECONDS = 90

# The wrap reasons /session/wrap will accept and persist. Kept as constants so the client,
# the server and the readout copy can never drift apart on a spelling.
WRAP_CAMERA_OFF = "camera_off"
WRAP_NO_ANSWER = "no_answer_timeout"
WRAP_SESSION_TIME_UP = "session_time_up"


def camera_grace_expired(seconds_camera_off) -> bool:
    """True once the camera has been off for the full grace and is STILL off.

    The client re-reports `camera_off` at that point, which walks the camera ladder one
    rung (nudge -> warn -> wrap). Turning the camera back on inside the grace clears the
    timer and nothing escalates — the grace is a real second chance, not a countdown.
    """
    try:
        return float(seconds_camera_off) >= CAMERA_GRACE_SECONDS
    except (TypeError, ValueError):
        return False


def is_abandonment(seconds_since_question, mic_live: bool, typed_chars: int = 0) -> bool:
    """Abandonment = an answer is due and BOTH channels have been silent for 90s.

    `mic_live` is True when the mic is UNMUTED — i.e. the candidate is still holding the
    channel open. Muting is their right, so a muted candidate who is typing is not
    abandoning; and neither is an unmuted candidate sitting quiet (they may simply be
    thinking, which is the per-question clock's business, and that ends in a skip and the
    next question — never in ending the session). Only the total dead end wraps.
    """
    if mic_live or int(typed_chars or 0) > 0:
        return False
    try:
        return float(seconds_since_question) >= SILENT_ABANDON_SECONDS
    except (TypeError, ValueError):
        return False


def wrap_directive() -> str:
    """Closing line when the interview ends early. Courteous — we are ending the
    session, not punishing the person."""
    return (
        "EARLY WRAP (this is your closing turn): the interview is ending early. In your own "
        "voice, close courteously: thank them, say plainly that you will wrap up with what "
        "you have covered, and tell them their feedback will follow. Do NOT scold, do NOT "
        "accuse, do NOT generate any report or scores — the debrief is produced separately."
    )


# ── Readout: "Professional presence" ─────────────────────────────────────────
#
# SCORING_CONTEXT item 9 — PRESENCE HAS NO BAND. It used to carry a readiness pill of its
# own, which meant the readout said "Interview-Ready" in two places, about two different
# things, and a learner had no way to know which one was the verdict. Worse, presence has
# never entered the benchmark (item 11 — it is report-only, and it stays that way), so its
# pill was a readiness claim made by something that does not score readiness.
#
# The band now lives in exactly ONE place: the Readiness block. This module reports counts
# and one coaching line. If you are reaching for presence_band() to render a pill, that is
# the bug this comment exists to stop.
_COACHING = {
    "tab_hidden": "You left the interview tab during the session. In a live panel, "
                  "looking away from the screen reads as disengagement — stay in the room.",
    "window_blur": "You switched away from the interview window. Close other apps before "
                   "a real interview so nothing pulls your focus.",
    "no_face": "You dropped out of frame during the interview. Set your camera up once, "
               "before you begin, and stay centred in it.",
    "multiple_faces": "More than one person appeared in frame. Sit somewhere you will not "
                      "be interrupted — a panel notices.",
    "looking_away": "You looked away from the camera often. Hold the interviewer's eye "
                    "while you think; it reads as composure, not hesitation.",
}


def presence_readout(by_type: dict, camera_at_join: bool) -> dict:
    """The readout's Professional-presence block. Counts only — never a judgement about
    the person, never an emotion label, and (since SCORING_CONTEXT item 9) never a band.

    When the learner joined camera-off, camera-based signals are omitted entirely: they
    were never measured, so they are never reported and never scored.
    """
    counts = {k: int(v) for k, v in (by_type or {}).items()
              if k in ATTENTION_SIGNALS and int(v or 0) > 0}
    if not camera_at_join:
        counts = {k: v for k, v in counts.items() if k not in CAMERA_SIGNALS}

    total = sum(counts.values())

    if total == 0:
        note = ("You stayed present throughout — no attention drift picked up. "
                "That is exactly how a panel wants to be met.")
    else:
        worst = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        note = _COACHING.get(worst, "Hold your attention on the interviewer throughout.")

    return {
        # The card renders on this, not on a band. Presence is REPORT-ONLY: it never
        # enters the benchmark and it never carries a readiness verdict of its own.
        "measured": True,
        "events_total": total,
        "by_type": counts,
        "coaching_note": note,
        # True when camera signals were not measured at all (camera-off join).
        "camera_signals_disabled": not camera_at_join,
    }


# ═════════════════════════════════════════════════════════════════════════════
#  PHASE D — expression / posture metrics (m1–m8)
# ═════════════════════════════════════════════════════════════════════════════
#
# WHERE THE NUMBERS COME FROM. In VIDEO mode the browser runs MediaPipe over the
# LOCAL camera frames, folds them into eight numbers, DISCARDS every frame, and
# sends only those eight at session close. This module — like every other line in
# this file — never sees an image, a video frame, or a facial landmark. It sees
# eight numbers and turns them into eight behaviour sentences. There is, by
# construction, no code path here that could accept media.
#
# REPORT-ONLY (hold this line in review). m1–m8 NEVER enter the Benchmark Score or
# the readiness band. They render inside the existing Presence Profile section and
# nowhere else. `presence_metrics_readout` returns counts and sentences — never a
# band, never a /10, never a factor. A camera-on session and the same session with
# the camera off must land on an identical band; a test pins exactly that.
#
# VIDEO ONLY, AND EVERY OTHER PATH IS A SILENT NO-OP. Metrics are computed only in
# VIDEO mode. AUDIO, TEXT, a camera-off join, or a MediaPipe that failed to load
# all degrade to the SAME thing: no metrics, no penalty, the session scored exactly
# as if this feature did not exist. `presence_metrics_readout` returns the no-data
# block for all of them — it is never an error, never a gap in the readout.
#
# BEHAVIOUR, NEVER EMOTION. Every metric maps to a sentence about something a panel
# could physically observe — "looked at the screen during most of the interview" —
# and never to a claim about how the person felt. "seemed nervous / bored /
# confident" is banned, and a test lints every sentence this module can emit.

# The closed set of metric keys, in reporting order. A payload key outside this set
# is dropped on the floor (see `sanitize_presence_metrics`) — the wire cannot smuggle
# a ninth field, a landmark array, or an emotion label into the store.
PRESENCE_METRIC_KEYS = ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8")

# "ratio"  -> a fraction of the session, clamped to [0.0, 1.0].
# "count"  -> a non-negative event tally, clamped to [0, PRESENCE_COUNT_CAP].
PRESENCE_COUNT_CAP = 999

# Per-metric spec. `label` is the tile caption; `kind` drives sanitisation and
# display; the sentence builders live below and are keyed by the same id. NOTHING
# here is an emotion word, and nothing downstream may add one.
PRESENCE_METRICS = (
    {"id": "m1", "key": "gaze_on_screen",     "kind": "ratio", "label": "Eye contact with screen"},
    {"id": "m2", "key": "head_pose_stability","kind": "ratio", "label": "Head steadiness"},
    {"id": "m3", "key": "posture_events",     "kind": "count", "label": "Posture shifts"},
    {"id": "m4", "key": "expression_variability","kind": "ratio","label": "Expression range"},
    {"id": "m5", "key": "smile_neutral_balance","kind": "ratio","label": "Time smiling"},
    {"id": "m6", "key": "blink_attention",    "kind": "ratio", "label": "Steady blink rate"},
    {"id": "m7", "key": "gesture_presence",   "kind": "ratio", "label": "Hand gestures"},
    {"id": "m8", "key": "framing_centering",  "kind": "ratio", "label": "Framing in shot"},
)
_METRIC_BY_ID = {m["id"]: m for m in PRESENCE_METRICS}

# ── Behaviour sentences ──────────────────────────────────────────────────────
# Three bands per ratio metric (high / mixed / low) and two per count metric. Each
# is a plain observation, the kind a panel would make out loud. Read them adversarially
# for emotion words — the lint below does, but the author has to first.
def _band3(v):
    """high / mixed / low for a [0,1] ratio."""
    if v >= 0.66:
        return "high"
    if v >= 0.33:
        return "mixed"
    return "low"


_RATIO_SENTENCES = {
    "m1": {
        "high": "You held your eyes on the screen for most of the interview — that reads as attention in a panel.",
        "mixed": "You looked at the screen for about half of the interview, and away for the rest.",
        "low": "You looked away from the screen for much of the interview. Setting your camera at eye level makes it easier to hold the interviewer's gaze.",
    },
    "m2": {
        "high": "You kept your head steady while you spoke.",
        "mixed": "Your head moved around a fair amount as you answered.",
        "low": "Your head moved around a lot during your answers. Sitting a little further back gives you room to stay settled in frame.",
    },
    "m4": {
        "high": "Your face was animated as you spoke — your expression changed with what you were saying.",
        "mixed": "Your expression changed some as you answered.",
        "low": "Your expression stayed mostly flat while you spoke. Letting your face move with your words helps a panel follow you.",
    },
    "m5": {
        "high": "You smiled during much of the interview.",
        "mixed": "You smiled at points and held a neutral expression the rest of the time.",
        "low": "You kept a neutral expression for most of the interview.",
    },
    "m6": {
        "high": "You blinked at a steady, natural rate throughout.",
        "mixed": "Your blink rate varied through the session.",
        "low": "Your blink rate was uneven across the session.",
    },
    "m7": {
        "high": "You used your hands as you spoke.",
        "mixed": "You used the occasional hand gesture while answering.",
        "low": "You kept your hands still for most of the interview. A little natural hand movement reads as engagement.",
    },
    "m8": {
        "high": "You stayed centred and well-framed in the shot.",
        "mixed": "You drifted around the frame at times during the interview.",
        "low": "You were often off-centre or partly out of frame. Framing yourself once before you start keeps you in shot.",
    },
}


def _sentence_for(metric_id: str, value) -> str:
    """The behaviour sentence for one metric at one value. Never an emotion claim."""
    spec = _METRIC_BY_ID.get(metric_id)
    if spec is None:
        return ""
    if spec["kind"] == "count":
        n = int(value)
        # m3 posture shifts — descriptive, not a verdict. Some shifting is normal.
        if n <= 3:
            return "You settled into one position and mostly stayed there."
        return f"You changed posture {n} times during the interview — a lot of shifting can pull a panel's eye away from your answer."
    return _RATIO_SENTENCES.get(metric_id, {}).get(_band3(float(value)), "")


def sanitize_presence_metrics(raw) -> dict | None:
    """Reduce whatever the client posted to EXACTLY the eight known numbers.

    The whole trust boundary for m1–m8 lives here. Ratios are coerced to floats and
    clamped to [0,1]; counts to non-negative ints under a cap. Any key outside
    PRESENCE_METRIC_KEYS is dropped, any non-numeric value drops that one metric, and
    a payload with none of the eight returns None (nothing to store, nothing to show).
    A landmark array, an emotion string, or a stray field cannot survive this call.
    """
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for spec in PRESENCE_METRICS:
        if spec["id"] not in raw:
            continue
        v = raw[spec["id"]]
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
            continue
        if spec["kind"] == "count":
            out[spec["id"]] = max(0, min(PRESENCE_COUNT_CAP, int(f)))
        else:
            out[spec["id"]] = max(0.0, min(1.0, round(f, 4)))
    return out or None


def _display_value(spec: dict, value) -> str:
    """The tile's short readout string — a percentage or a count, never a score."""
    if spec["kind"] == "count":
        return str(int(value))
    return f"{round(float(value) * 100)}%"


def presence_metrics_available(session_mode, camera_at_join: bool, metrics) -> bool:
    """True only when there are real m1–m8 to show: VIDEO mode, camera on at join,
    and a sanitised payload with at least one metric. Every other path is a no-op —
    and NOT a penalty (D6)."""
    if str(session_mode or "").strip().upper() != "VIDEO":
        return False
    if not camera_at_join:
        return False
    return bool(sanitize_presence_metrics(metrics))


# The one line shown when there is deliberately nothing to show. It is not an
# apology and not a gap — a camera-off join (or a mode without a camera, or a
# MediaPipe that never loaded) is a supported path, and the copy says so.
PRESENCE_METRICS_NO_DATA = "No presence data — camera was off. Presence is never scored, so nothing here counted for or against you."


def presence_metrics_readout(metrics, session_mode, camera_at_join: bool) -> dict:
    """The m1–m8 sub-block of the Presence Profile. REPORT-ONLY — no band, no score.

    Returns {"measured": False, "note": <no-data line>} for every path that has no
    metrics to show (AUDIO/TEXT, camera-off, MediaPipe failure). Returns the eight
    behaviour rows only for a VIDEO session that actually produced numbers. The caller
    renders this INSIDE the existing Presence Profile section — never as a new section.
    """
    if not presence_metrics_available(session_mode, camera_at_join, metrics):
        return {"measured": False, "note": PRESENCE_METRICS_NO_DATA}

    clean = sanitize_presence_metrics(metrics) or {}
    rows = []
    for spec in PRESENCE_METRICS:
        if spec["id"] not in clean:
            continue
        v = clean[spec["id"]]
        rows.append({
            "id": spec["id"],
            "label": spec["label"],
            "kind": spec["kind"],
            "display": _display_value(spec, v),
            "behaviour": _sentence_for(spec["id"], v),
        })
    return {
        "measured": True,
        # Named so a reviewer skimming the readout payload cannot miss it: this block
        # is descriptive only and touches no score.
        "report_only": True,
        "metrics": rows,
    }
