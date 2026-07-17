#!/usr/bin/env python3
"""SYNTHETIC STUDENT DRIVER — Capacity/Cost phase, item 1.

Runs a full interview end-to-end with NO human: mints a dev token, starts a session, fetches
the greeting, answers every question the stage machine poses with scripted-but-realistic
answers, handles the confidence-rating gates, and finishes through /session/end so the debrief
and benchmark actually write. It is the workhorse both the cost matrix (item 3) and the
capacity ramp (item 4) drive; run it on its own to prove one session of any mode works.

  TEXT   — typed answers submitted straight to /session/turn (no mic, no TTS/STT spend).
  AUDIO  — each answer is a pre-synthesised spoken-answer WAV fed to /session/stt (the REAL
  VIDEO    Sarvam STT path), whose transcript is then submitted as the turn. VIDEO is AUDIO
           plus camera_at_join; the answer path is identical.

The WAV bank is built ONCE (TTS → ffmpeg → 16k mono WAV), content-addressed on disk under the
scratch dir, and reused across every AUDIO/VIDEO session forever after.

Usage:
    python scripts/synthetic_student.py --mode TEXT --duration 20
    python scripts/synthetic_student.py --mode AUDIO --duration 45 --difficulty Realistic
    BACKEND_URL=https://upskill25-mock-test.hf.space python scripts/synthetic_student.py --mode TEXT

Lives under scripts/ and is not named test_*, so pytest never collects it.
"""
import argparse
import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")  # ₹ and — on a cp1252 console
except Exception:
    pass
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402  (load_env, ENV_PATH)
from app.dev_auth import build_dev_token  # noqa: E402

DEFAULT_BASE = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# A small bank of substantive, STAR-shaped answers. Every one clears the "substantive answer"
# gate (not an "I don't know"), so a driven session always has enough evidence for the billed
# debrief to run. Picked deterministically by (stage, index) so a session is reproducible.
ANSWER_BANK = [
    "In my final year I led a team of four to rebuild our college fest's registration portal. "
    "The old one crashed every year on launch day. I profiled the bottleneck to unindexed "
    "queries, added the right indexes and a small cache, and we handled about three thousand "
    "signups in the first hour with no downtime.",
    "I once inherited a payments reconciliation script that silently dropped about two percent "
    "of transactions. I added end-to-end logging, traced it to a timezone bug at the day "
    "boundary, wrote a regression test, and backfilled the missing records over a weekend.",
    "When a teammate and I disagreed on whether to refactor or ship, I proposed we time-box a "
    "spike: two days to prove the refactor paid off. It did on the hot path, so we refactored "
    "that and shipped the rest. Framing it as a measurable experiment took the heat out of it.",
    "For a machine-learning course project I built a churn model. The naive version overfit "
    "badly, so I added cross-validation, pruned features by importance, and got the validation "
    "F1 from about 0.61 to 0.78. I documented the tradeoffs so the next student could build on it.",
    "During an internship I noticed our nightly job took six hours and often failed. I broke it "
    "into idempotent stages with checkpoints, parallelised the independent ones, and cut it to "
    "about ninety minutes. More importantly, a failure now retried one stage instead of the whole run.",
    "I mentor two juniors on my open-source project. The hardest part is resisting the urge to "
    "just fix their PRs myself. Instead I leave a failing test and a hint, and let them find it. "
    "Both of them now review other people's code, which is the outcome I actually wanted.",
    "A stakeholder wanted a feature I thought would confuse users. Rather than argue, I built a "
    "quick clickable prototype and ran it past five people. Three got stuck at the same step, "
    "which gave us the real conversation. We shipped a simpler version and adoption was higher.",
    "My biggest weakness is that I go deep on a problem and lose track of time. I've started "
    "time-boxing investigations and writing down what I've ruled out, so even when I stop I "
    "leave a clear trail. It also makes it far easier to hand work off when I need to.",
]


def _answer_for(stage: str, idx: int, duration_min: int) -> str:
    """A deterministic answer for this (stage, index). For longer target durations we lengthen
    the answer (two bank entries stitched together) so a 45-minute session realistically speaks
    and generates more than a 10-minute one — which is the whole point of the duration axis."""
    base = ANSWER_BANK[idx % len(ANSWER_BANK)]
    if duration_min >= 40:
        base = base + " " + ANSWER_BANK[(idx + 3) % len(ANSWER_BANK)]
    elif duration_min >= 18:
        base = base + " To add one more angle: " + ANSWER_BANK[(idx + 5) % len(ANSWER_BANK)].split(".")[0] + "."
    return base


# ── The reusable spoken-answer WAV bank (built once) ─────────────────────────

def _bank_dir() -> Path:
    d = Path(os.environ.get(
        "SYNTH_WAV_BANK",
        str(Path(__file__).resolve().parent.parent
            / "backend" / "tts_cache" / "synth_answer_bank"),
    ))
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_answer_wav(text: str, voice: str = "ritu") -> Path | None:
    """TTS `text`, transcode to 16k mono WAV, and cache it content-addressed. Returns the path,
    or None (with a printed reason) if ffmpeg or TTS/SARVAM_API_KEY is unavailable."""
    key = hashlib.sha256(("v1|" + voice + "|" + text).encode("utf-8")).hexdigest()[:16]
    out = _bank_dir() / f"{key}.wav"
    if out.exists() and out.stat().st_size > 0:
        return out
    if not shutil.which("ffmpeg"):
        print("  (no ffmpeg on PATH — cannot build the spoken-answer WAV bank)")
        return None
    try:
        from app import tts
        mp3 = asyncio.run(tts.synthesize(text, tts.Voice(speaker=voice, pace=1.0)))
    except Exception as e:
        print(f"  (TTS synth failed: {type(e).__name__}: {e})")
        return None
    if not mp3:
        print("  (TTS returned no audio — is SARVAM_API_KEY set and TTS reachable?)")
        return None
    src = out.with_suffix(".mp3.tmp")
    src.write_bytes(mp3)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                        "-ac", "1", "-ar", "16000", str(out)],
                       capture_output=True, text=True)
    try:
        src.unlink()
    except OSError:
        pass
    if r.returncode != 0 or not out.exists():
        print(f"  (ffmpeg encode failed: {r.stderr[:200]})")
        return None
    return out


def prewarm_bank(duration_min: int, voice: str = "ritu") -> int:
    """Build every WAV a session at this duration could use, up front. Returns the count built
    (or already cached). Best-effort — a missing ffmpeg/key just returns 0 and AUDIO falls back."""
    built = 0
    for stage in ("WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE", "REVERSE", "FEEDBACK"):
        for idx in range(8):
            wav = build_answer_wav(_answer_for(stage, idx, duration_min), voice)
            if wav:
                built += 1
            else:
                return built
    return built


# ── Auth ─────────────────────────────────────────────────────────────────────

def mint_token() -> str:
    env = mdt.load_env(mdt.ENV_PATH)
    secret = env.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("no JWT_SECRET in backend/.env — cannot mint a synthetic token")
    token, _ = build_dev_token(
        secret, days=1, audience=env.get("JWT_AUDIENCE", ""), issuer=env.get("JWT_ISSUER", ""),
    )
    return token


# ── Driving one full session ──────────────────────────────────────────────────

TERMINAL_STAGES = {"READOUT", "DONE"}
RATING_STAGES = {"DOMAIN", "BEHAVIOURAL", "CASE"}


def drive_session(
    client: httpx.Client,
    base: str,
    token: str,
    *,
    mode: str = "TEXT",
    duration_min: int = 20,
    difficulty: str = "Realistic",
    feedback: str = "interview",
    role: str = "Software Engineer",
    level: str = "Fresher",
    voice: str = "female",
    max_turns: int = 40,
    verbose: bool = False,
) -> dict:
    """Run ONE interview to completion. Returns a result dict:
        {ok, session_id, mode, turns, answers, scored, elapsed_s, per_turn_latency_ms:[...],
         errors:[...]}.
    Never raises for an interview-level failure — it records it in `errors` and returns, so a
    ramp of many sessions is never sunk by one bad session."""
    headers = {"Authorization": "Bearer " + token}
    result = {"ok": False, "session_id": None, "mode": mode, "turns": 0, "answers": 0,
              "scored": None, "elapsed_s": 0.0, "per_turn_latency_ms": [], "errors": []}
    t_start = time.time()
    audio_capable = mode in ("AUDIO", "VIDEO")
    speaker = "shubh" if voice == "male" else "ritu"

    def log(msg):
        if verbose:
            print(msg)

    try:
        # 1) start
        body = {
            "role": role, "level": level, "duration_min": duration_min,
            "difficulty": difficulty, "mode": feedback, "session_mode": mode,
            "voice": voice, "camera_at_join": mode == "VIDEO",
        }
        r = client.post(f"{base}/session/start", json=body, headers=headers)
        if r.status_code == 503 and (r.json() or {}).get("detail", {}).get("capacity_full"):
            result["errors"].append("capacity_hold")   # the safety valve held us — expected under load
            return result
        if r.status_code != 200:
            result["errors"].append(f"start {r.status_code}: {r.text[:200]}")
            return result
        sid = r.json()["session_id"]
        result["session_id"] = sid
        log(f"  session {sid[:8]} start ({mode}, {duration_min}min, {difficulty})")

        # 1b) consent (AUDIO/VIDEO need voice_recording before /session/stt is allowed)
        if audio_capable:
            client.post(f"{base}/consent", headers=headers,
                        json={"consent_type": "voice_recording", "copy_version": "synthetic-driver"})

        # 2) greeting (the kickoff LLM)
        r = client.post(f"{base}/session/greeting", json={"session_id": sid, "voice": voice}, headers=headers)
        if r.status_code != 200:
            result["errors"].append(f"greeting {r.status_code}: {r.text[:200]}")
            return result

        # 3) state
        r = client.get(f"{base}/session/{sid}/state", headers=headers)
        state = r.json() if r.status_code == 200 else {}
        stage = state.get("current_stage", "WARMUP")
        stt_unavailable_logged = False

        for turn_i in range(max_turns):
            if stage in TERMINAL_STAGES or state.get("status") not in (None, "active"):
                break
            answer = _answer_for(stage, turn_i, duration_min)

            # AUDIO/VIDEO: run the answer through the REAL STT path first, use its transcript.
            if audio_capable:
                wav = build_answer_wav(answer, speaker)
                transcript = None
                if wav:
                    with open(wav, "rb") as f:
                        files = {"audio": ("answer.wav", f.read(), "audio/wav")}
                    # duration_seconds is what the ledger meters for STT — 16k mono WAV.
                    dur = os.path.getsize(wav) / (16000 * 2)
                    rs = client.post(f"{base}/session/stt", headers=headers, files=files,
                                     data={"session_id": sid, "duration_seconds": f"{dur:.1f}"})
                    if rs.status_code == 200:
                        transcript = (rs.json() or {}).get("transcript")
                    elif not stt_unavailable_logged:
                        stt_unavailable_logged = True
                        log(f"    STT unavailable ({rs.status_code}) — typing the answer instead")
                # Fall back to typing the same answer if STT is off/failed — the turn still happens.
                answer = transcript or answer

            t0 = time.perf_counter()
            r = client.post(f"{base}/session/turn", headers=headers,
                            json={"session_id": sid, "message": answer, "stage": stage, "voice": voice})
            result["per_turn_latency_ms"].append(int((time.perf_counter() - t0) * 1000))
            if r.status_code == 409:
                # stage drifted under us — resync and retry once without counting it.
                rr = client.get(f"{base}/session/{sid}/state", headers=headers)
                state = rr.json() if rr.status_code == 200 else state
                stage = state.get("current_stage", stage)
                continue
            if r.status_code != 200:
                result["errors"].append(f"turn {r.status_code}: {r.text[:160]}")
                break
            result["turns"] += 1
            result["answers"] += 1
            state = r.json().get("state", {})

            # Rating gate: DOMAIN/BEHAVIOURAL/CASE answers must be rated before we move on.
            if state.get("awaiting_rating") and state.get("last_answer_id"):
                client.post(f"{base}/session/turn/rating", headers=headers,
                            json={"session_id": sid, "answer_id": state["last_answer_id"], "rating": 3})
                rr = client.get(f"{base}/session/{sid}/state", headers=headers)
                if rr.status_code == 200:
                    state = rr.json()
            stage = state.get("current_stage", stage)

        # 4) end — the billed debrief + benchmark write here.
        r = client.post(f"{base}/session/end", json={"session_id": sid}, headers=headers)
        if r.status_code != 200:
            result["errors"].append(f"end {r.status_code}: {r.text[:200]}")
            return result
        result["scored"] = bool((r.json() or {}).get("scored"))
        result["ok"] = True
        log(f"  session {sid[:8]} done: {result['answers']} answers, scored={result['scored']}")
    except httpx.HTTPError as e:
        result["errors"].append(f"http {type(e).__name__}: {e}")
    finally:
        result["elapsed_s"] = round(time.time() - t_start, 1)
    return result


def read_ledger_from_db(session_id: str) -> dict | None:
    """Read the stored cost_ledger straight from the (shared Aiven) DB. Used by the cost-matrix
    runner — the Space writes the ledger to the same DB this machine can reach. None if the
    column/row is missing."""
    try:
        from sqlalchemy import text
        from app.db import engine
        import json as _json
        with engine.connect() as conn:
            row = conn.execute(text("SELECT cost_ledger FROM vyom_sessions WHERE id=:id"),
                               {"id": session_id}).first()
        if not row or not row[0]:
            return None
        v = row[0]
        return v if isinstance(v, dict) else _json.loads(v)
    except Exception as e:
        print(f"  (ledger DB read failed: {type(e).__name__}: {e})")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Drive a full synthetic interview end-to-end.")
    ap.add_argument("--mode", choices=["TEXT", "AUDIO", "VIDEO"], default="TEXT")
    ap.add_argument("--duration", type=int, default=20)
    ap.add_argument("--difficulty", choices=["Easy", "Realistic", "Stretch", "Critical"], default="Realistic")
    ap.add_argument("--feedback", choices=["interview", "coach"], default="interview")
    ap.add_argument("--role", default="Software Engineer")
    ap.add_argument("--level", default="Fresher")
    ap.add_argument("--voice", choices=["female", "male"], default="female")
    ap.add_argument("--count", type=int, default=1, help="how many sessions to run in sequence")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--read-ledger", action="store_true", help="read the stored cost_ledger from DB after each session")
    args = ap.parse_args()

    print(f"Target backend : {args.base}")
    print(f"Config         : mode={args.mode} duration={args.duration} difficulty={args.difficulty} "
          f"feedback={args.feedback} role={args.role!r} level={args.level!r} count={args.count}")

    if args.mode in ("AUDIO", "VIDEO"):
        n = prewarm_bank(args.duration, "shubh" if args.voice == "male" else "ritu")
        print(f"Answer WAV bank: {n} clip(s) ready" if n else
              "Answer WAV bank: UNAVAILABLE (no ffmpeg/SARVAM) — AUDIO answers will fall back to typed")

    try:
        token = mint_token()
    except Exception as e:
        print(f"FAIL: {e}")
        return 1

    ok = 0
    with httpx.Client(timeout=240.0) as client:
        for i in range(args.count):
            res = drive_session(
                client, args.base, token,
                mode=args.mode, duration_min=args.duration, difficulty=args.difficulty,
                feedback=args.feedback, role=args.role, level=args.level, voice=args.voice,
                verbose=True,
            )
            status = "PASS" if res["ok"] else "FAIL"
            print(f"[{i+1}/{args.count}] {status} session={res['session_id']} turns={res['turns']} "
                  f"scored={res['scored']} elapsed={res['elapsed_s']}s errors={res['errors']}")
            if res["ok"]:
                ok += 1
            if args.read_ledger and res["session_id"]:
                led = read_ledger_from_db(res["session_id"])
                if led:
                    print(f"      ledger: ₹{led['total_inr']}  "
                          f"(llm ₹{led['llm']['total_inr']}, tts ₹{led['tts']['inr']}, stt ₹{led['stt']['inr']})")
                else:
                    print("      ledger: not found in DB (migration 011 applied? same DB as the backend?)")

    print(f"\n{ok}/{args.count} session(s) completed successfully.")
    return 0 if ok == args.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
