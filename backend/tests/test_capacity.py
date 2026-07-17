"""The safety valve — MAX_CONCURRENT_SESSIONS and the polite hold (Capacity/Cost item 5).

Beyond the cap a NEW session gets an in-brand HOLD (503, structured detail), never an error,
and sessions already running are never touched. The feature is inert until ops sets a real
cap (item 4's measured knee). These tests drive _check_capacity against a fake DB reporting a
configurable live-session count, plus assert the exact approved copy.

Runnable with:  python -m pytest tests/test_capacity.py
           or:  python tests/test_capacity.py
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

APPROVED_COPY = "Every panel is in session right now. Give us a few minutes — your seat is coming."


class _Row:
    def __init__(self, n):
        self.n = n


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class FakeDB:
    """Reports `live` active sessions in the window, and records whether it was queried."""
    def __init__(self, live):
        self.live = live
        self.executed = 0

    def execute(self, stmt, params=None):
        self.executed += 1
        return _Result(_Row(self.live))


def _with_cap(cap, fn):
    orig = m.settings.MAX_CONCURRENT_SESSIONS
    m.settings.MAX_CONCURRENT_SESSIONS = cap
    try:
        return fn()
    finally:
        m.settings.MAX_CONCURRENT_SESSIONS = orig


# ── The default ships DARK ───────────────────────────────────────────────────

def test_default_cap_is_zero_unlimited():
    """No env override -> 0 -> the valve is inert. Asserted against config's own fallback."""
    import importlib
    import dotenv
    from app import config as cfg

    saved_env = os.environ.pop("MAX_CONCURRENT_SESSIONS", None)
    saved_load = dotenv.load_dotenv
    dotenv.load_dotenv = lambda *a, **k: False
    try:
        importlib.reload(cfg)
        assert cfg.Settings().MAX_CONCURRENT_SESSIONS == 0
    finally:
        dotenv.load_dotenv = saved_load
        if saved_env is not None:
            os.environ["MAX_CONCURRENT_SESSIONS"] = saved_env
        importlib.reload(cfg)


def test_cap_zero_never_queries_or_holds():
    db = FakeDB(9999)
    _with_cap(0, lambda: m._check_capacity(db))     # must not raise
    assert db.executed == 0, "an unset cap must not even count live sessions"


# ── Cap reached -> polite hold ───────────────────────────────────────────────

def test_at_cap_holds_with_503_and_structured_detail():
    db = FakeDB(10)   # 10 live, cap 10 -> full
    with pytest.raises(HTTPException) as ei:
        _with_cap(10, lambda: m._check_capacity(db))
    exc = ei.value
    assert exc.status_code == 503
    assert isinstance(exc.detail, dict)
    assert exc.detail["capacity_full"] is True
    # Never styled as an error: a Retry-After lets the client back off politely.
    assert exc.headers and exc.headers.get("Retry-After")


def test_over_cap_holds():
    db = FakeDB(25)
    with pytest.raises(HTTPException) as ei:
        _with_cap(10, lambda: m._check_capacity(db))
    assert ei.value.status_code == 503


def test_hold_copy_is_the_approved_one_liner():
    db = FakeDB(10)
    with pytest.raises(HTTPException) as ei:
        _with_cap(10, lambda: m._check_capacity(db))
    msg = ei.value.detail["message"]
    assert msg == APPROVED_COPY
    # One line, and never the word "error".
    assert "\n" not in msg
    assert "error" not in msg.lower()


# ── Slot frees -> entry works ────────────────────────────────────────────────

def test_below_cap_admits():
    db = FakeDB(9)   # a seat just freed: 9 live under a cap of 10
    _with_cap(10, lambda: m._check_capacity(db))   # must not raise
    assert db.executed > 0, "under the cap we still count, then admit"


def test_empty_house_admits():
    db = FakeDB(0)
    _with_cap(5, lambda: m._check_capacity(db))     # must not raise


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
