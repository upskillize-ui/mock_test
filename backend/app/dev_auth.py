"""Dev-only JWT minting — the SINGLE source of truth shared by:
  - scripts/make_dev_token.py (CLI),
  - scripts/debug_token.py (diagnostic),
  - scripts/e2e_smoke.py (end-to-end proof),
  - GET /dev/login (backend auto-login route).

Stdlib only (hmac/base64/json) so scripts can import it without pulling the whole
app, and so there is exactly ONE claim set + signing path that everything reuses —
no drift between the tool and the verifier (app/auth.py).

SECURITY: this only *builds* tokens; it does not decide when to expose them. The
/dev/login route that serves one is gated to APP_ENV=development in app/main.py.
"""
import base64
import hashlib
import hmac
import json
import time


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_token(secret: str, payload: dict) -> str:
    """Sign an HS256 JWT for `payload` with `secret` (stdlib HMAC-SHA256)."""
    header = {"alg": "HS256", "typ": "JWT"}
    seg = lambda obj: _b64url(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{seg(header)}.{seg(payload)}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{_b64url(sig)}"


def build_payload(sub: str, name: str, email: str, days: int,
                  audience: str = "", issuer: str = "") -> dict:
    """The EXACT claim set every dev path mints. auth.py needs `exp` (mandatory) and
    one of sub/user_id/id — both are always present here. aud/iss are added only when
    the backend enforces them, mirroring app/auth.py's conditional checks."""
    now = int(time.time())
    payload = {
        "sub": sub,
        "user_id": sub,
        "full_name": name,
        "name": name,
        "email": email,
        "iat": now,
        "exp": now + days * 86400,
    }
    if audience:
        payload["aud"] = audience
    if issuer:
        payload["iss"] = issuer
    return payload


def build_dev_token(secret: str, sub: str = "dev-user-1", name: str = "Dev Tester",
                    email: str = "dev@upskillize.local", days: int = 30,
                    audience: str = "", issuer: str = ""):
    """Build (token, payload) with the shared claim + signing logic. 30-day default."""
    payload = build_payload(sub, name, email, days, audience=audience, issuer=issuer)
    return make_token(secret, payload), payload


# The localStorage key the frontend reads the token from. The token must be stored
# under the FRONTEND origin, so the frontend's dev receiver (main.jsx) writes this key.
FRONTEND_TOKEN_KEY = "upskillize_token"

# The URL-fragment name the token is handed off in (kept in sync with main.jsx).
DEV_TOKEN_FRAGMENT = "dev_token"


def dev_login_redirect_url(frontend_origin: str, token: str) -> str:
    """Build the cross-origin handoff URL: {frontend}/#dev_token=<jwt>.

    localStorage is PER-ORIGIN — a token written on the backend origin (localhost:8000)
    is invisible to the frontend origin (localhost:5173). So /dev/login 302-redirects
    to the frontend with the token in a URL FRAGMENT, and a dev-only receiver in the
    frontend entry (main.jsx) stores it under FRONTEND_TOKEN_KEY on its OWN origin,
    strips the fragment, and reloads. Fragments are never sent to servers or logged.
    """
    return frontend_origin.rstrip("/") + "/#" + DEV_TOKEN_FRAGMENT + "=" + token
