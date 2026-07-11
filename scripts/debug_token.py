#!/usr/bin/env python3
"""Definitive dev-token diagnostic.

(a) Builds a token with make_dev_token's EXACT logic (build_dev_token).
(b) Validates it through the EXACT path the request flow uses — app.auth.current_user
    — same secret source (app.config.settings), same algorithm, same required claims.
(c) Prints PASS, or the precise failure (expired / signature mismatch / missing claim /
    audience mismatch / malformed), plus a secret-source and claim-by-claim comparison.

    python scripts/debug_token.py

The secret is never printed — only its length and a short SHA-256 fingerprint, so we
can tell whether the signer's secret and the verifier's secret are the same value.
"""
import hashlib
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))       # for `app.*`
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for `make_dev_token`

# Surface auth.py's dev-only rejection reason (INFO) on the console.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

import make_dev_token as mdt  # noqa: E402
from jose import jwt, JWTError  # noqa: E402


def fp(secret: str) -> str:
    """Non-reversible fingerprint of a secret: length + short SHA-256 prefix."""
    if not secret:
        return "EMPTY"
    return f"len={len(secret)} sha256[:10]={hashlib.sha256(secret.encode()).hexdigest()[:10]}"


def main() -> int:
    from app.config import settings  # imported here so config errors surface cleanly

    env = mdt.load_env(mdt.ENV_PATH)
    script_secret = env.get("JWT_SECRET", "")
    verifier_secret = settings.JWT_SECRET

    print("=== 1. Secret source comparison ===")
    print(f"make_dev_token reads : {mdt.ENV_PATH}")
    print(f"  script secret      : {fp(script_secret)}")
    print(f"  auth/config secret : {fp(verifier_secret)}  (from app.config.settings.JWT_SECRET)")
    same = script_secret == verifier_secret and bool(script_secret)
    print(f"  MATCH              : {'YES' if same else 'NO  <-- signer and verifier disagree!'}")
    print(f"  JWT_ALGORITHM      : script=HS256  auth={settings.JWT_ALGORITHM}")
    print(f"  JWT_AUDIENCE       : env={env.get('JWT_AUDIENCE')!r}  auth={settings.JWT_AUDIENCE!r}")
    print(f"  JWT_ISSUER         : env={env.get('JWT_ISSUER')!r}  auth={settings.JWT_ISSUER!r}")
    print(f"  APP_ENV            : {settings.APP_ENV}")

    print("\n=== 2. Build token (make_dev_token's exact logic) ===")
    if not script_secret:
        print("FAIL: no JWT_SECRET in backend/.env — cannot sign.")
        return 1
    token, payload = mdt.build_dev_token(env, script_secret)
    print(f"  claims: {sorted(payload.keys())}")

    print("\n=== 3. Decode with auth.py's exact kwargs (direct jose, precise error) ===")
    kwargs = {"algorithms": [settings.JWT_ALGORITHM],
              "options": {"require": ["exp"], "verify_exp": True}}
    if settings.JWT_AUDIENCE:
        kwargs["audience"] = settings.JWT_AUDIENCE
    if settings.JWT_ISSUER:
        kwargs["issuer"] = settings.JWT_ISSUER
    direct_ok = False
    try:
        jwt.decode(token, verifier_secret, **kwargs)
        direct_ok = True
        print("  direct jose.decode: OK")
    except JWTError as e:
        print(f"  direct jose.decode: FAIL -> {type(e).__name__}: {e}")

    print("\n=== 4. Validate through the real request path (app.auth.current_user) ===")
    from app.auth import current_user
    from fastapi import HTTPException
    flow_ok = False
    try:
        uid = current_user("Bearer " + token)
        flow_ok = True
        print(f"  current_user: OK -> user_id={uid!r}")
    except HTTPException as e:
        print(f"  current_user: 401 -> {e.detail}")

    print("\n=== 5. Where will the frontend SEND this token? ===")
    # The token is signed with the LOCAL backend/.env secret. If the frontend targets a
    # DIFFERENT backend, that backend verifies with ITS OWN secret -> signature 401,
    # even though the token is perfectly valid here. Vite bakes VITE_* at dev-server
    # start, so a page reload alone won't repoint it — the dev server must restart.
    HOSTED_DEFAULT = "https://upskill25-mock-test.hf.space"
    fe_env = mdt.load_env(ROOT / "frontend" / ".env")
    target = fe_env.get("VITE_INTERVIEWIQ_API_URL") or fe_env.get("VITE_API_URL") or HOSTED_DEFAULT
    is_local = ("localhost" in target) or ("127.0.0.1" in target)
    print(f"  frontend/.env target : {target}")
    print(f"  default if unset     : {HOSTED_DEFAULT} (hosted — different JWT_SECRET)")
    if not is_local:
        print("  WARNING: frontend targets a NON-LOCAL backend. This local token will 401")
        print("           there (that backend has a different secret). Point the frontend")
        print("           at your local backend and RESTART `npm run dev`.")
    else:
        print("  OK: frontend/.env targets local — but confirm `npm run dev` was RESTARTED")
        print("      after this file was set (Vite reads .env only at startup, not on reload).")

    print("\n=== RESULT ===")
    if direct_ok and flow_ok:
        print("PASS — the minted token validates through the exact auth path.")
        print("The token/auth logic is correct; a live 401 is an ENV/TARGET issue (see step 5).")
        print("\n--- ready-to-paste browser login line ---")
        print(f'localStorage.setItem("{mdt.FRONTEND_TOKEN_KEY}", "{token}"); location.reload();')
        return 0
    print("FAIL — see the precise reason above.")
    if not same:
        print("Most likely cause: the verifier's JWT_SECRET != the signer's JWT_SECRET.")
        print("Check for a JWT_SECRET set in the OS environment — python-dotenv does NOT")
        print("override an already-set env var, so a stale shell/system JWT_SECRET would")
        print("shadow backend/.env for the running backend while the script reads the file.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
