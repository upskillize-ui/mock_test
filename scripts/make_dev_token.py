"""Generate a local dev JWT so the app treats you as a logged-in test user.

Signs an HS256 token with the JWT_SECRET from backend/.env — the SAME secret the
backend verifies with (app/auth.py) — using the SHARED builder in app/dev_auth.py,
so the tool can never drift from what the backend mints/verifies.

Usage (from the repo root or anywhere):
    python scripts/make_dev_token.py
    python scripts/make_dev_token.py --sub my-id --name "Asha K" --email asha@test.local --days 30

Then paste the printed localStorage command into your browser console (F12) on the
running frontend tab, and reload. (Or, even simpler in development, just open
http://localhost:8000/dev/login — no paste needed.)
"""
import argparse
import sys
from pathlib import Path

# backend/.env lives one level up from scripts/ then into backend/.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
ENV_PATH = BACKEND / ".env"
sys.path.insert(0, str(BACKEND))  # so we can import the shared app.dev_auth builder

from app.dev_auth import build_dev_token, FRONTEND_TOKEN_KEY  # noqa: E402


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

    token, _ = build_dev_token(
        secret, sub=args.sub, name=args.name, email=args.email, days=args.days,
        audience=env.get("JWT_AUDIENCE", ""), issuer=env.get("JWT_ISSUER", ""),
    )

    print("\n=== InterviewIQ dev token ===")
    print(f"user:  {args.sub}  ({args.email})")
    print(f"valid: {args.days} day(s)\n")
    print("TOKEN:\n" + token + "\n")
    print("To log in, open the frontend (http://localhost:5173), press F12,")
    print("open the Console tab, paste this line, press Enter, then reload:\n")
    print(f'localStorage.setItem("{FRONTEND_TOKEN_KEY}", "{token}"); location.reload();\n')
    print("Or simplest (development): just open http://localhost:8000/dev/login\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
