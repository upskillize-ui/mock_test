"""Tests for the dev auto-login route + shared dev-token builder.

Guarantees GET /dev/login is registered ONLY in development (absent in prod/other
envs), that a minted dev token validates through the real verifier, and that the
served page wires up localStorage + redirect.

Runnable with:  python -m pytest tests/test_dev_login.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI  # noqa: E402

from app import main as m  # noqa: E402
from app import dev_auth  # noqa: E402


def _paths(app):
    return {r.path for r in app.routes}


def test_dev_login_registered_only_in_development():
    orig = m.settings.APP_ENV
    try:
        # Not registered outside development (prod, the test 'dev' shorthand, anything else).
        for env in ("production", "dev", "staging", ""):
            m.settings.APP_ENV = env
            app = FastAPI()
            assert m.register_dev_login(app) is False, env
            assert "/dev/login" not in _paths(app), env
        # Registered only for the exact 'development' value backend/.env uses.
        m.settings.APP_ENV = "development"
        app = FastAPI()
        assert m.register_dev_login(app) is True
        assert "/dev/login" in _paths(app)
    finally:
        m.settings.APP_ENV = orig


def test_minted_dev_token_validates_through_real_verifier():
    from app.auth import current_user
    token, _ = dev_auth.build_dev_token(m.settings.JWT_SECRET, sub="dev-user-1", days=1)
    assert current_user("Bearer " + token) == "dev-user-1"


def test_dev_login_html_wires_localstorage_and_redirect():
    html = dev_auth.dev_login_html("header.payload.sig", "http://localhost:5173")
    assert "localStorage.setItem" in html
    assert "upskillize_token" in html
    assert "header.payload.sig" in html
    assert "http://localhost:5173" in html


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL  {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
