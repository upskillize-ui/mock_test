"""Generate a local dev JWT so the app treats you as a logged-in test user.

Stdlib only (no pip install needed). Signs an HS256 token with the JWT_SECRET
from backend/.env — the SAME secret the backend verifies with (app/auth.py).

Usage (from the repo root or anywhere):
    python scripts/make_dev_token.py
    python scripts/make_dev_token.py --sub my-id --name "Asha K" --email asha@test.local --days 30

Then paste the printed localStorage command into your browser console (F12) on
the running frontend tab, and reload.
"""
import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

# backend/.env lives one level up from scripts/ then into backend/.
ENV_PATH = Path(__file__).resolve().parent.parent / "backend" / ".env"
FRONTEND_TOKEN_KEY = "upskillize_token"  # App.jsx reads this localStorage key.


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_token(secret: str, payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    seg = lambda obj: b64url(json.dumps(obj, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{seg(header)}.{seg(payload)}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{signing_input.decode('ascii')}.{b64url(sig)}"


def build_payload(env: dict, sub: str, name: str, email: str, days: int) -> dict:
    """The EXACT claim set this script mints. Shared with scripts/debug_token.py so
    the diagnostic validates the identical payload the tool produces."""
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
    # If the backend enforces audience/issuer, mirror them so the token validates.
    if env.get("JWT_AUDIENCE"):
        payload["aud"] = env["JWT_AUDIENCE"]
    if env.get("JWT_ISSUER"):
        payload["iss"] = env["JWT_ISSUER"]
    return payload


def build_dev_token(env: dict, secret: str, sub="dev-user-1",
                    name="Dev Tester", email="dev@upskillize.local", days=7):
    """Build (token, payload) using this script's exact signing + claim logic."""
    payload = build_payload(env, sub, name, email, days)
    return make_token(secret, payload), payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a local dev JWT for InterviewIQ.")
    ap.add_argument("--sub", default="dev-user-1", help="user id (goes in 'sub')")
    ap.add_argument("--name", default="Dev Tester", help="full name shown in the UI")
    ap.add_argument("--email", default="dev@upskillize.local", help="email shown in the UI")
    ap.add_argument("--days", type=int, default=7, help="token validity in days")
    ap.add_argument("--secret", default=None, help="override JWT_SECRET (else read from backend/.env)")
    args = ap.parse_args()

    env = load_env(ENV_PATH)
    secret = args.secret or env.get("JWT_SECRET", "")

    if not secret or secret == "PASTE_LMS_JWT_SECRET_HERE":
        print("ERROR: JWT_SECRET is not set.", file=sys.stderr)
        print(f"Fill JWT_SECRET in {ENV_PATH} (or pass --secret ...) and re-run.", file=sys.stderr)
        return 1

    if (env.get("JWT_ALGORITHM", "HS256") or "HS256").upper() != "HS256":
        print("ERROR: this script only signs HS256 tokens.", file=sys.stderr)
        return 1

    token, payload = build_dev_token(
        env, secret, sub=args.sub, name=args.name, email=args.email, days=args.days
    )

    print("\n=== InterviewIQ dev token ===")
    print(f"user:  {args.sub}  ({args.email})")
    print(f"valid: {args.days} day(s)\n")
    print("TOKEN:\n" + token + "\n")
    print("To log in, open the frontend (http://localhost:5173), press F12,")
    print("open the Console tab, paste this line, press Enter, then reload:\n")
    print(f'localStorage.setItem("{FRONTEND_TOKEN_KEY}", "{token}"); location.reload();\n')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
