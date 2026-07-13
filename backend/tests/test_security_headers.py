"""Tests for the security-headers middleware CSP policy.

Strict CSP everywhere (script-src 'self', no CDN) EXCEPT /docs and /redoc, which are
relaxed to allow the jsDelivr CDN so Swagger/ReDoc render. /dev/login is NOT exempted
— its script is an external same-origin file, so it keeps the strict policy.

Runnable with:  python -m pytest tests/test_security_headers.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _csp(path):
    return client.get(path).headers.get("content-security-policy", "")


def test_strict_csp_on_api_routes():
    # /openapi.json is a normal app route (no DB) — strict CSP, no CDN allowance.
    csp = _csp("/openapi.json")
    assert "script-src 'self'" in csp
    assert "cdn.jsdelivr.net" not in csp
    assert "frame-ancestors 'none'" in csp


def test_docs_and_redoc_allow_jsdelivr():
    for path in ("/docs", "/redoc"):
        csp = _csp(path)
        assert "https://cdn.jsdelivr.net" in csp, path
        assert "script-src 'self' https://cdn.jsdelivr.net" in csp, path
        # still locked down otherwise
        assert "frame-ancestors 'none'" in csp, path


def test_dev_login_path_keeps_strict_csp():
    # /dev/login is not a docs path, so it must keep the STRICT CSP (its script is an
    # external same-origin file — 'self' already allows it). The route is 404 in this
    # test env (APP_ENV != 'development'); the middleware still applies the strict CSP.
    csp = _csp("/dev/login")
    assert "script-src 'self'" in csp
    assert "cdn.jsdelivr.net" not in csp
