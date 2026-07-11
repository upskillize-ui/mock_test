#!/usr/bin/env python3
"""Voice Phase 3 Part A — live TTS diagnostic (run manually, hits the real vendor).

Loads backend/.env, then:
  1. Does a RAW POST to Sarvam with the exact v3 payload we build, printing the
     HTTP status and full response body (so a 4xx explains precisely what v3
     rejected — bad speaker, unknown field, quota, auth).
  2. Calls the real app.tts.synthesize("Hello, welcome to your interview.", "ritu")
     and reports the decoded byte count (or the failure).

The API key is never printed. This is the hard gate for Phase 3: it must return
audio bytes before mic-in-all-rounds / delivery work proceeds.

    python scripts/test_tts.py
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")

# Surface tts.py's own warning logs (status + body) on the console.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

import httpx  # noqa: E402

from app import tts  # noqa: E402
from app.config import settings  # noqa: E402

SENTENCE = "Hello, welcome to your interview."
SPEAKER = "ritu"


def _raw_probe() -> None:
    """Raw POST with the real build_payload — prints status + full body."""
    if not settings.SARVAM_API_KEY:
        print("FAIL: SARVAM_API_KEY is not set in backend/.env")
        return
    payload = tts.build_payload(SENTENCE, SPEAKER)
    printable = {k: v for k, v in payload.items() if k != "text"}
    print(f"\n--- RAW PROBE ---\nURL: {tts._SARVAM_URL}\nPayload (text omitted): {printable}")
    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        r = httpx.post(tts._SARVAM_URL, headers=headers, json=payload, timeout=30.0)
    except Exception as e:
        print(f"RAW PROBE transport error: {type(e).__name__}: {e}")
        return
    print(f"HTTP {r.status_code}")
    if r.status_code == 200:
        try:
            audios = r.json().get("audios") or []
            print(f"OK: audios[]={len(audios)} entries; first entry base64 len="
                  f"{len(audios[0]) if audios else 0}")
        except Exception as e:
            print(f"200 but could not parse audios: {type(e).__name__}: {e}\nBody: {r.text[:800]}")
    else:
        print(f"ERROR BODY: {r.text[:1200]}")


def _synthesize_path() -> int:
    """Exercise the real async synthesize() wrapper."""
    print("\n--- synthesize() PATH ---")
    audio = asyncio.run(tts.synthesize(SENTENCE, SPEAKER))
    if audio:
        print(f"SUCCESS: synthesize() returned {len(audio)} audio bytes")
        out = ROOT / "scripts" / "_tts_probe_out.mp3"
        try:
            out.write_bytes(audio)
            print(f"Wrote sample to {out} — play it to confirm it's real audio.")
        except OSError:
            pass
        return 0
    print("FAILURE: synthesize() returned None — see the RAW PROBE body above for the reason.")
    return 1


if __name__ == "__main__":
    print(f"Model={settings.TTS_MODEL} lang={settings.TTS_LANG} "
          f"speaker={SPEAKER} rate={settings.TTS_SAMPLE_RATE} "
          f"temp={settings.TTS_TEMPERATURE} pace={settings.TTS_PACE}")
    _raw_probe()
    sys.exit(_synthesize_path())
