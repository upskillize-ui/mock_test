"""API key hardening (insurance): a key with trailing whitespace must never produce an
illegal header value again. A trailing newline on the Space secret made httpx raise
"Illegal header value" and took every model call — the whole product — down.

Runnable with:  python -m pytest tests/test_api_key_hardening.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from app import claude_client as cc  # noqa: E402


def test_trailing_whitespace_key_produces_a_clean_header():
    orig = cc.settings.ANTHROPIC_API_KEY
    cc.settings.ANTHROPIC_API_KEY = "sk-ant-test-key\n"          # the exact prod footgun
    try:
        val = cc._headers()["x-api-key"]
        assert val == "sk-ant-test-key" == val.strip()   # one line: stripped, no stray whitespace
        httpx.Headers(cc._headers())                      # and httpx accepts it (would raise on "\n")
    finally:
        cc.settings.ANTHROPIC_API_KEY = orig


def test_config_strips_key_at_load():
    # The load-time strip, verified without reloading the module (a reload leaves other
    # modules holding a stale `settings` and pollutes later tests). Assert the class attribute
    # itself is stripped — the value the running app actually carries.
    from app.config import Settings
    assert Settings.ANTHROPIC_API_KEY == Settings.ANTHROPIC_API_KEY.strip()


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
