#!/usr/bin/env python3
"""Measure the ONE number the founder actually felt: click "Start interview" ->
first audible word.

Drives the RUNNING local backend over HTTP, exactly the way the browser does, and
times each leg of the path:

  BEFORE (one blocking call):
      POST /session/start   -- kickoff LLM + EVERY greeting sentence synthesised
      GET  /session/audio/{hash of sentence 1}   -- the bytes the <audio> element needs
      first audible word = start + audio-fetch

  AFTER (the room renders on the session row; the greeting streams):
      POST /session/start      -- the session row. THE ROOM RENDERS HERE.
      POST /session/greeting   -- kickoff LLM + sentence ONE only
      GET  /session/audio/{...}
      first audible word = start + greeting + audio-fetch
      (sentences 2..n synthesise via /session/speech WHILE sentence one plays)

Auto-detects which backend it is talking to (does /session/greeting exist?), so the
same script produces both halves of the before/after table.

    python scripts/measure_start_latency.py           # 3 runs, prints the median
    RUNS=5 python scripts/measure_start_latency.py

Not named test_*, and lives under scripts/, so pytest never collects it.
"""
import os
import statistics
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
RUNS = int(os.environ.get("RUNS", "3"))

# The founder's config, as the UAT session ran it.
CONFIG = {
    "name": "Candidate",
    "role": "Software Engineer (SDE)",
    "level": "Fresher",
    "company": "Razorpay",
    "duration_min": 20,
    "difficulty": "Realistic",
    "mode": "interview",
    "round": "full",
    "voice": "female",
    "interviewer_name": "Riya",
    "camera_at_join": True,
}


def _token() -> str:
    env = mdt.load_env(mdt.ENV_PATH)
    secret = env.get("JWT_SECRET", "")
    if not secret:
        print("FAIL: no JWT_SECRET in backend/.env")
        raise SystemExit(1)
    tok, _ = build_dev_token(secret, days=1, audience=env.get("JWT_AUDIENCE", ""),
                             issuer=env.get("JWT_ISSUER", ""))
    return tok


def _first_url(segments) -> str | None:
    for s in segments or []:
        if s.get("audio_url"):
            return s["audio_url"]
    return None


def one_run(client, headers, split: bool) -> dict:
    """One cold session. Returns the leg timings in seconds."""
    t0 = time.perf_counter()
    r = client.post(f"{BASE}/session/start", json=CONFIG, headers=headers)
    r.raise_for_status()
    body = r.json()
    t_start = time.perf_counter() - t0
    sid = body["session_id"]

    segments = body.get("audio_segments") or []
    t_greet = 0.0

    if split:
        # AFTER: the room is already on screen. Now the greeting streams in.
        t1 = time.perf_counter()
        g = client.post(f"{BASE}/session/greeting",
                        json={"session_id": sid, "voice": CONFIG["voice"]}, headers=headers)
        g.raise_for_status()
        gbody = g.json()
        t_greet = time.perf_counter() - t1
        segments = gbody.get("audio_segments") or []

    url = _first_url(segments)
    if not url:
        print("  WARNING: no audio_url on any greeting segment — is TTS_ENABLED on?")
        return {"start": t_start, "greeting": t_greet, "audio": 0.0,
                "first_word": t_start + t_greet, "sentences": len(segments)}

    t2 = time.perf_counter()
    a = client.get(f"{BASE}{url}", headers=headers)
    a.raise_for_status()
    t_audio = time.perf_counter() - t2

    return {
        "start": t_start,
        "greeting": t_greet,
        "audio": t_audio,
        "first_word": t_start + t_greet + t_audio,
        "sentences": len(segments),
        "clip_bytes": len(a.content),
    }


def main() -> int:
    headers = {"Authorization": "Bearer " + _token()}
    try:
        with httpx.Client(timeout=120.0) as client:
            # Does this backend have the split? Ask its OpenAPI schema — probing the route
            # itself is ambiguous (a real /session/greeting 404s for an unknown session id,
            # which is exactly what a missing route looks like).
            schema = client.get(f"{BASE}/openapi.json").json()
            split = "/session/greeting" in (schema.get("paths") or {})
            shape = "AFTER (start + greeting split)" if split else "BEFORE (one blocking start)"
            print(f"Target : {BASE}")
            print(f"Shape  : {shape}")
            print(f"Runs   : {RUNS}  (each a COLD session - a fresh greeting is never a cache hit)\n")

            rows = []
            for i in range(RUNS):
                row = one_run(client, headers, split)
                rows.append(row)
                print(f"  run {i+1}: start={row['start']:.2f}s  greeting={row['greeting']:.2f}s  "
                      f"audio={row['audio']:.2f}s  ->  FIRST WORD {row['first_word']:.2f}s  "
                      f"({row['sentences']} sentences)")

            def med(k):
                return statistics.median(r[k] for r in rows)

            print("\n  -- median --------------------------------")
            print(f"  POST /session/start        {med('start'):.2f}s"
                  + ("   <- THE ROOM RENDERS HERE" if split else "   (room blocked until here)"))
            if split:
                print(f"  POST /session/greeting     {med('greeting'):.2f}s")
            print(f"  GET  /session/audio/{{..}}   {med('audio'):.2f}s")
            print(f"  === CLICK -> FIRST AUDIBLE WORD   {med('first_word'):.2f}s")
            if split:
                print(f"  === CLICK -> ROOM ON SCREEN       {med('start'):.2f}s")

    except httpx.ConnectError:
        print(f"\nBACKEND NOT REACHABLE at {BASE} — start it first:")
        print("  cd backend && py -m uvicorn app.main:app --port 8000")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
