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
