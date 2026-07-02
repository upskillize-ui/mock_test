"""InterviewIQ compliance + resume helpers — pure logic, no DB or I/O.

Kept side-effect-free so the staleness check (INT-06), retention-window math and
consent-gate logic (INT-07) are trivially unit-testable with mocked datetimes.

Concerns covered:
  - Resume staleness: is an active session idle past the threshold?
  - Retention windows: which artefacts are past their DPDPA retention window?
  - Right-to-erasure: when does a soft-deleted account get hard-purged?
  - Consent gate: may a session start given the current consent + feature flags?
  - PII redaction: scrub emails/phone-like strings before anything hits a log.
"""

import re
from datetime import datetime, timedelta

# INT-06: an active session untouched for this long is offered as resume-or-restart.
DEFAULT_IDLE_MINUTES = 30

# INT-07: right-to-erasure grace window. A soft-deleted account is recoverable for
# this many days, then hard-purged by the nightly job.
DEFAULT_DELETE_GRACE_DAYS = 30


# ── INT-06: resume staleness ────────────────────────────────────────────────

def is_stale(last_activity: datetime | None, now: datetime,
             idle_minutes: int = DEFAULT_IDLE_MINUTES) -> bool:
    """True when the last message is older than `idle_minutes` (idle session).

    A session with no messages yet (last_activity is None) is NOT stale — it has
    only just started. Comparison is naive-datetime based (DB stores naive UTC).
    """
    if last_activity is None:
        return False
    return (now - last_activity) > timedelta(minutes=idle_minutes)


# ── INT-07: retention windows ───────────────────────────────────────────────

def should_purge_messages(status: str | None, ended_at: datetime | None,
                          now: datetime, transcript_days: int) -> bool:
    """Transcript hard-delete rule.

    We purge message rows only for sessions that have actually finished
    (completed or abandoned) AND whose end is older than the transcript window.
    Active/unfinished sessions are never purged, regardless of age.
    """
    if status not in ("completed", "abandoned"):
        return False
    if ended_at is None:
        return False
    return (now - ended_at) > timedelta(days=transcript_days)


def should_purge_debrief(ended_at: datetime | None, now: datetime,
                         debrief_days: int) -> bool:
    """Debrief hard-delete rule — kept far longer than transcripts (the learner's
    scorecard is the durable value), but still bounded by DEBRIEF_RETENTION_DAYS.
    """
    if ended_at is None:
        return False
    return (now - ended_at) > timedelta(days=debrief_days)


def should_hard_delete_account(deleted_at: datetime | None, now: datetime,
                               grace_days: int = DEFAULT_DELETE_GRACE_DAYS) -> bool:
    """Right-to-erasure: a soft-deleted account (deleted_at set) is hard-purged
    once the recovery grace window has elapsed."""
    if deleted_at is None:
        return False
    return (now - deleted_at) > timedelta(days=grace_days)


# ── INT-07: consent gate ────────────────────────────────────────────────────

def consent_gate_ok(voice_enabled: bool, has_active_consent: bool) -> bool:
    """May a session start?

    Voice mode is DPDPA-sensitive (audio capture), so it requires a recorded,
    active consent row. While VOICE_ENABLED is false the gate is a no-op and every
    session is allowed — the machinery is built now and switches on with voice.
    """
    if not voice_enabled:
        return True
    return has_active_consent


# ── INT-07: PII redaction for logs ──────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Long digit runs (phone / Aadhaar-like); keep short numbers (scores, counts).
_PHONE_RE = re.compile(r"\b(?:\+?\d[\d\-\s]{7,}\d)\b")


def redact(text: str) -> str:
    """Scrub emails and phone-like digit runs from a string before it is logged.

    Defensive: this is applied at log-write, so even if an upstream error body or
    stack trace happens to echo learner-entered contact details they never land
    in the log file.
    """
    if not text:
        return text
    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _PHONE_RE.sub("[redacted-number]", text)
    return text
