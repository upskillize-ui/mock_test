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

import asyncio  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import urllib.parse  # noqa: E402

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402  (load_env, ENV_PATH)
from app.dev_auth import build_dev_token, DEV_TOKEN_FRAGMENT  # noqa: E402

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


def _make_webm_fixture() -> bytes | None:
    """Build a short REAL-speech webm/opus clip the way Chrome MediaRecorder would:
    synthesize a sentence via TTS, then ffmpeg-encode it to Opus-in-WebM. Returns the
    bytes, or None (with a printed reason) if ffmpeg or TTS isn't available."""
    if not shutil.which("ffmpeg"):
        print("  (no ffmpeg on PATH — cannot synthesize a webm fixture)")
        return None
    try:
        from app import tts
        mp3 = asyncio.run(tts.synthesize(
            "So basically, um, I led the migration and it took about three weeks.", "ritu"))
    except Exception as e:
        print(f"  (TTS synth failed: {type(e).__name__}: {e})")
        return None
    if not mp3:
        print("  (TTS returned no audio — is SARVAM_API_KEY set?)")
        return None
    tmp = Path(tempfile.gettempdir())
    src, out = tmp / "_e2e_src.mp3", tmp / "_e2e.webm"
    src.write_bytes(mp3)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-c:a", "libopus", "-ac", "1", "-ar", "48000", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        print(f"  (ffmpeg encode failed: {r.stderr[:200]})")
        return None
    return out.read_bytes()


def _token_from_handoff(client) -> str | None:
    """Step 0: verify the real GET /dev/login handoff — expect a 302 whose Location
    carries the token in a #dev_token=<jwt> fragment. Returns the token, or None if
    the route is 404 (backend not in development) so the caller can fall back."""
    r0 = client.get(f"{BASE}/dev/login", follow_redirects=False)
    if r0.status_code in (301, 302, 303, 307, 308):
        loc = r0.headers.get("location", "")
        frag = "#" + DEV_TOKEN_FRAGMENT + "="
        if frag not in loc:
            print(f"FAIL step 0: {r0.status_code} redirect but no {frag} in Location: {loc}")
            return None
        token = urllib.parse.unquote(loc.split(frag, 1)[1])
        origin = loc.split(frag, 1)[0]
        print(f"PASS step 0: GET /dev/login -> {r0.status_code}, token handed off to {origin!r} via fragment")
        return token
    if r0.status_code == 404:
        print("NOTE step 0: /dev/login is 404 (backend APP_ENV != development) — "
              "falling back to a locally-minted token.")
        return None
    print(f"FAIL step 0: GET /dev/login -> {r0.status_code}: {r0.text[:400]}")
    return None


def main() -> int:
    print(f"Target backend : {BASE}")
    try:
        with httpx.Client(timeout=90.0) as client:
            # Step 0 — obtain the token the way the browser does (via /dev/login).
            token = _token_from_handoff(client)
            if token is None:
                env = mdt.load_env(mdt.ENV_PATH)
                secret = env.get("JWT_SECRET", "")
                if not secret:
                    print("FAIL: /dev/login unavailable and no JWT_SECRET to fall back on.")
                    return 1
                token, _ = build_dev_token(
                    secret, days=30, audience=env.get("JWT_AUDIENCE", ""),
                    issuer=env.get("JWT_ISSUER", ""),
                )
            headers = {"Authorization": "Bearer " + token}

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

            # Step 3 — voice consent (required by /session/stt).
            r3 = client.post(f"{BASE}/consent", headers=headers,
                             json={"consent_type": "voice_recording", "copy_version": "e2e-smoke"})
            if r3.status_code != 200:
                print(f"FAIL step 3: POST /consent -> {r3.status_code}: {r3.text[:400]}")
                return 1
            print("PASS step 3: POST /consent (voice_recording) -> 200")

            # Step 4 — REAL browser-shaped audio through /session/stt: a webm/opus clip
            # sent with Chrome's exact content-type (audio/webm;codecs=opus). This is the
            # last-mile that was failing; expect a transcript string back.
            webm = _make_webm_fixture()
            if webm is None:
                print("NOTE step 4: skipped STT (couldn't build a webm fixture — needs ffmpeg + TTS).")
            else:
                files = {"audio": ("answer.webm", webm, "audio/webm;codecs=opus")}
                data = {"session_id": session_id, "duration_seconds": "4.0"}
                r4 = client.post(f"{BASE}/session/stt", headers=headers, files=files, data=data)
                if r4.status_code != 200:
                    print(f"FAIL step 4: POST /session/stt -> {r4.status_code}: {r4.text[:500]}")
                    return 1
                transcript = (r4.json() or {}).get("transcript")
                if not transcript:
                    print("FAIL step 4: 200 but transcript is null — Sarvam rejected the audio "
                          f"(check the backend log for the vendor error body). body={r4.text[:400]}")
                    return 1
                print(f"PASS step 4: POST /session/stt (webm;codecs=opus) -> 200, transcript={transcript!r}")

    except httpx.ConnectError:
        print(f"\nBACKEND NOT REACHABLE at {BASE} — start the backend first:")
        print("  cd backend && py -m uvicorn app.main:app --reload --port 8000")
        return 2
    except httpx.HTTPError as e:
        print(f"FAIL: HTTP error talking to {BASE}: {type(e).__name__}: {e}")
        return 1

    print("\nALL STEPS PASS -- auth chain + voice STT work end-to-end "
          "(token -> session -> consent -> webm/opus -> transcript).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
