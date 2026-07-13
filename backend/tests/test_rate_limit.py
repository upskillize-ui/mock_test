"""INT-09 daily-session cap — enforced in production, bypassed in development.

The cap is the production cost-abuse guard and must stay intact. It is skipped ONLY
when APP_ENV == "development", so local UAT (which burns sessions quickly) is never
blocked. In dev we don't even touch the DB — the session is neither counted nor checked.

Runnable with:  python -m pytest tests/test_rate_limit.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app import main as m  # noqa: E402


class _Row:
    def __init__(self, n):
        self.session_count = n


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeDB:
    """Reports `count` sessions used today, and records whether it was touched at all."""
    def __init__(self, count):
        self.count = count
        self.executed = 0

    def execute(self, stmt, params=None):
        self.executed += 1
        if "SELECT session_count" in str(stmt):
            return _Result(_Row(self.count))
        return _Result(None)

    def commit(self):
        pass


def _with_env(env, fn):
    orig = m.settings.APP_ENV
    m.settings.APP_ENV = env
    try:
        return fn()
    finally:
        m.settings.APP_ENV = orig


# ── Configured limits ───────────────────────────────────────────────────────

def test_default_daily_session_cap_is_20():
    """The DEFAULT (no env override) is 20 sessions per student per day.

    Asserted against the config's own fallback, not the ambient env: we drop the var
    and stub out dotenv so backend/.env can't re-inject a value and mask the default.
    """
    import importlib
    import dotenv
    from app import config as cfg

    saved_env = os.environ.pop("MAX_SESSIONS_PER_DAY", None)
    saved_load = dotenv.load_dotenv
    dotenv.load_dotenv = lambda *a, **k: False    # stop .env repopulating the var
    try:
        importlib.reload(cfg)
        assert cfg.Settings().MAX_SESSIONS_PER_DAY == 20
    finally:
        dotenv.load_dotenv = saved_load
        if saved_env is not None:
            os.environ["MAX_SESSIONS_PER_DAY"] = saved_env
        importlib.reload(cfg)


def test_answers_per_session_cap_unchanged_at_20():
    # A different limit entirely — raising the daily session cap must not move it.
    assert m.settings.MAX_ANSWERS_PER_SESSION == 20


def test_limit_copy_names_the_number_from_config():
    """The 429 copy must interpolate the configured cap, never hardcode it."""
    over = m.settings.MAX_SESSIONS_PER_DAY + 1
    db = FakeDB(over)
    with pytest.raises(HTTPException) as ei:
        _with_env("production", lambda: m._check_rate_limit(db, "u1"))
    assert f"Daily limit of {m.settings.MAX_SESSIONS_PER_DAY} interviews reached" in str(ei.value.detail)


# ── Production: the cap is intact ───────────────────────────────────────────

def test_cap_enforced_in_production_when_over_limit():
    over = m.settings.MAX_SESSIONS_PER_DAY + 1
    db = FakeDB(over)

    def go():
        with pytest.raises(HTTPException) as ei:
            m._check_rate_limit(db, "u1")
        assert ei.value.status_code == 429
        assert "Daily limit" in str(ei.value.detail)

    _with_env("production", go)
    assert db.executed > 0, "production must still count + check the session"


def test_cap_allows_under_limit_in_production():
    db = FakeDB(m.settings.MAX_SESSIONS_PER_DAY)   # exactly at the cap -> still allowed
    _with_env("production", lambda: m._check_rate_limit(db, "u1"))


def test_cap_still_enforced_for_any_non_development_env():
    # Only the exact "development" value bypasses — staging/dev-shorthand must not.
    over = m.settings.MAX_SESSIONS_PER_DAY + 5
    for env in ("production", "staging", "dev"):
        db = FakeDB(over)
        with pytest.raises(HTTPException):
            _with_env(env, lambda: m._check_rate_limit(db, "u1"))


# ── Development: bypassed entirely ──────────────────────────────────────────

def test_cap_bypassed_in_development():
    db = FakeDB(m.settings.MAX_SESSIONS_PER_DAY * 100)   # far over the cap
    _with_env("development", lambda: m._check_rate_limit(db, "u1"))   # must not raise
    assert db.executed == 0, "development must not even count the session"
