"""Unit tests for Phase 0 completion: INT-06 staleness + INT-07 retention/consent/redaction.

Pure-logic tests against app/compliance.py — no DB, mocked datetimes.

Runnable with either:  python -m pytest tests/test_phase0.py
                  or:  python tests/test_phase0.py
"""
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import compliance as c  # noqa: E402

NOW = datetime(2026, 7, 2, 12, 0, 0)


# ── INT-06: resume staleness ────────────────────────────────────────────────

def test_staleness_fresh_session_not_stale():
    # Last message 5 minutes ago -> still fresh.
    assert c.is_stale(NOW - timedelta(minutes=5), NOW, 30) is False


def test_staleness_idle_session_is_stale():
    # Last message 31 minutes ago, threshold 30 -> stale.
    assert c.is_stale(NOW - timedelta(minutes=31), NOW, 30) is True


def test_staleness_boundary_exactly_threshold_not_stale():
    # Exactly 30 min is NOT past the window (strict > comparison).
    assert c.is_stale(NOW - timedelta(minutes=30), NOW, 30) is False


def test_staleness_no_messages_not_stale():
    # A just-started session with no messages yet is never stale.
    assert c.is_stale(None, NOW, 30) is False


# ── INT-07: retention-window math ───────────────────────────────────────────

def test_messages_purged_only_when_finished_and_old():
    ended_old = NOW - timedelta(days=91)
    ended_recent = NOW - timedelta(days=10)
    # completed + past 90 days -> purge.
    assert c.should_purge_messages("completed", ended_old, NOW, 90) is True
    assert c.should_purge_messages("abandoned", ended_old, NOW, 90) is True
    # completed but within window -> keep.
    assert c.should_purge_messages("completed", ended_recent, NOW, 90) is False
    # active sessions are never purged, regardless of age.
    assert c.should_purge_messages("active", ended_old, NOW, 90) is False
    # no ended_at -> keep.
    assert c.should_purge_messages("completed", None, NOW, 90) is False


def test_messages_purge_boundary():
    # Exactly 90 days is within the window (strict > comparison) -> keep.
    assert c.should_purge_messages("completed", NOW - timedelta(days=90), NOW, 90) is False
    assert c.should_purge_messages("completed", NOW - timedelta(days=90, seconds=1), NOW, 90) is True


def test_debrief_kept_longer_than_transcript():
    ended = NOW - timedelta(days=100)
    # Past the 90-day transcript window...
    assert c.should_purge_messages("completed", ended, NOW, 90) is True
    # ...but well within the 365-day debrief window -> debrief kept.
    assert c.should_purge_debrief(ended, NOW, 365) is False
    # Past 365 days -> debrief purged.
    assert c.should_purge_debrief(NOW - timedelta(days=400), NOW, 365) is True


def test_account_hard_delete_after_grace():
    # Soft-deleted 31 days ago, 30-day grace -> hard delete.
    assert c.should_hard_delete_account(NOW - timedelta(days=31), NOW, 30) is True
    # Within grace -> keep (recoverable).
    assert c.should_hard_delete_account(NOW - timedelta(days=10), NOW, 30) is False
    # Not soft-deleted at all -> never.
    assert c.should_hard_delete_account(None, NOW, 30) is False


# ── INT-07: consent gate ────────────────────────────────────────────────────

def test_consent_gate_noop_when_voice_disabled():
    # Voice off -> always allowed, consent or not.
    assert c.consent_gate_ok(False, False) is True
    assert c.consent_gate_ok(False, True) is True


def test_consent_gate_enforced_when_voice_enabled():
    # Voice on -> requires an active consent row.
    assert c.consent_gate_ok(True, False) is False
    assert c.consent_gate_ok(True, True) is True


# ── INT-07: PII redaction ───────────────────────────────────────────────────

def test_redact_email_and_phone():
    out = c.redact("contact me at asha.k@example.com or +91 98765 43210 please")
    assert "asha.k@example.com" not in out
    assert "98765" not in out
    assert "[redacted-email]" in out
    assert "[redacted-number]" in out


def test_redact_keeps_short_numbers():
    # Scores/counts must survive — only long digit runs are masked.
    out = c.redact("overall 87 score with 3 answers")
    assert "87" in out and "3" in out


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
