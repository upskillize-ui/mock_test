#!/usr/bin/env python3
"""End-to-end auth proof — no browser, no human, no copy-paste.

Mints a token with the SHARED builder (app.dev_auth.build_dev_token) and drives the
RUNNING local backend over HTTP:
  1. POST /session/start   (Authorization: Bearer <token>)  -> expect 200 + session_id
  2. GET  /session/{id}/state                                -> expect 200 + current_stage

Prints PASS/FAIL per step with status codes, and the response body on failure. If the
backend isn't running it says so clearly instead of dumping a stack trace.

    python scripts/e2e_smoke.py            # against http://localhost:8000
    BACKEND_URL=http://localhost:8000 python scripts/e2e_smoke.py

Not named test_*, and lives under scripts/, so pytest never collects it.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402  (load_env, ENV_PATH)
from app.dev_auth import build_dev_token  # noqa: E402

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


def main() -> int:
    env = mdt.load_env(mdt.ENV_PATH)
    secret = env.get("JWT_SECRET", "")
    if not secret:
        print("FAIL: no JWT_SECRET in backend/.env — cannot mint a token.")
        return 1
    token, _ = build_dev_token(
        secret, days=30, audience=env.get("JWT_AUDIENCE", ""), issuer=env.get("JWT_ISSUER", "")
    )
    headers = {"Authorization": "Bearer " + token}
    print(f"Target backend : {BASE}")

    try:
        with httpx.Client(timeout=90.0) as client:
            # Step 1 — POST /session/start
            body = {"role": "Software Engineer", "level": "Fresher"}
            r1 = client.post(f"{BASE}/session/start", json=body, headers=headers)
            if r1.status_code != 200:
                print(f"FAIL step 1: POST /session/start -> {r1.status_code}")
                print(f"  body: {r1.text[:800]}")
                if r1.status_code == 401:
                    print("  (401 = auth chain broken — check the backend console for the "
                          "auth.py reason, and that this token matches THIS backend's JWT_SECRET.)")
                return 1
            session_id = (r1.json() or {}).get("session_id")
            if not session_id:
                print(f"FAIL step 1: 200 but no session_id in body: {r1.text[:400]}")
                return 1
            print(f"PASS step 1: POST /session/start -> 200, session_id={session_id}")

            # Step 2 — GET /session/{id}/state
            r2 = client.get(f"{BASE}/session/{session_id}/state", headers=headers)
            if r2.status_code != 200:
                print(f"FAIL step 2: GET /session/{{id}}/state -> {r2.status_code}")
                print(f"  body: {r2.text[:800]}")
                return 1
            stage = (r2.json() or {}).get("current_stage")
            if not stage:
                print(f"FAIL step 2: 200 but no current_stage in body: {r2.text[:400]}")
                return 1
            print(f"PASS step 2: GET /session/{{id}}/state -> 200, current_stage={stage}")

    except httpx.ConnectError:
        print(f"\nBACKEND NOT REACHABLE at {BASE} — start the backend first:")
        print("  cd backend && py -m uvicorn app.main:app --reload --port 8000")
        return 2
    except httpx.HTTPError as e:
        print(f"FAIL: HTTP error talking to {BASE}: {type(e).__name__}: {e}")
        return 1

    print("\nALL STEPS PASS -- the auth chain works end-to-end (token -> 200 -> session state).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
