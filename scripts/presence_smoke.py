#!/usr/bin/env python3
"""PRESENCE PHASE end-to-end smoke: drive the RUNNING backend the way the room does.

Proves the four server-side things this sprint shipped actually work over HTTP, against a
real DB, a real LLM and a real voice vendor — not just against their unit tests:

  1. FAST START   — /session/start returns a session row and no greeting; /session/greeting
                    returns the opening with sentence ONE already synthesised and the rest
                    marked pending; /session/speech fills those in from an INDEX.
  2. CLIP PACK    — /session/clips serves the acknowledgment + backchannel clips, and the
                    audio actually fetches.
  3. ENGAGEMENT   — two timed-out skips produce a CHECK-IN (not the next question); a third
                    silence WRAPS the interview courteously and routes to the readout.
  4. CRITICAL     — a pressure-panel session starts, and its turns come back in the
                    "critical" register.

    python scripts/presence_smoke.py

Not named test_*, and lives under scripts/, so pytest never collects it.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

BASE_CFG = {
    "name": "Asha", "role": "Credit Risk Analyst", "level": "Fresher",
    "company": "ICICI", "duration_min": 20, "mode": "interview", "round": "full",
    "voice": "female", "interviewer_name": "Riya", "camera_at_join": True,
}

ok = True


def check(label, cond, detail=""):
    global ok
    if cond:
        print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
    else:
        ok = False
        print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))


def token():
    env = mdt.load_env(mdt.ENV_PATH)
    t, _ = build_dev_token(env["JWT_SECRET"], days=1,
                           audience=env.get("JWT_AUDIENCE", ""), issuer=env.get("JWT_ISSUER", ""))
    return t


def main() -> int:
    h = {"Authorization": "Bearer " + token()}
    with httpx.Client(timeout=120.0) as c:

        # ── 1. FAST START ────────────────────────────────────────────────────
        print("\n1. FAST START")
        r = c.post(f"{BASE}/session/start", json={**BASE_CFG, "difficulty": "Realistic"}, headers=h)
        r.raise_for_status()
        s = r.json()
        sid = s["session_id"]
        check("/session/start returns a session row", bool(sid), sid[:8])
        check("...and NO greeting (the room renders on this)", s["greeting"] == "" and not s["audio_segments"])

        g = c.post(f"{BASE}/session/greeting", json={"session_id": sid, "voice": "female"}, headers=h)
        g.raise_for_status()
        gb = g.json()
        segs = gb["audio_segments"]
        check("/session/greeting returns the opening", bool(gb["greeting"]), gb["greeting"][:48] + "...")
        check("sentence 1 has audio, ready to play", bool(segs[0]["audio_url"]))
        check("later sentences are marked pending, not failed",
              all(s2["pending"] and s2["audio_url"] is None for s2 in segs[1:]),
              f"{len(segs)} sentences")
        check("the opening is 2-3 sentences, like every other turn", len(segs) <= 4, f"{len(segs)}")

        a = c.get(f"{BASE}{segs[0]['audio_url']}", headers=h)
        check("the first clip actually fetches", a.status_code == 200 and len(a.content) > 1000,
              f"{len(a.content)} bytes")

        sp = c.post(f"{BASE}/session/speech",
                    json={"session_id": sid, "voice": "female", "from_index": 1}, headers=h)
        sp.raise_for_status()
        rest = sp.json()["segments"]
        check("/session/speech fills in the rest, by INDEX",
              len(rest) == len(segs) - 1 and all(x["audio_url"] for x in rest),
              f"{len(rest)} clips")

        # Idempotence: a double-fire must not buy a second kickoff / a second interviewer.
        g2 = c.post(f"{BASE}/session/greeting", json={"session_id": sid, "voice": "female"}, headers=h)
        check("/session/greeting is idempotent (no second LLM bill)",
              g2.json()["greeting"] == gb["greeting"])

        # ── 2. THE CLIP PACK ─────────────────────────────────────────────────
        print("\n2. CLIP PACK (acknowledgments + backchannels)")
        cp = c.get(f"{BASE}/session/clips?voice=female", headers=h)
        cp.raise_for_status()
        pack = cp.json()
        check("8 acknowledgment clips", len(pack["acks"]) == 8,
              ", ".join(x["text"] for x in pack["acks"]))
        check("backchannel clips", len(pack["backchannels"]) == 2,
              ", ".join(x["text"] for x in pack["backchannels"]))
        ac = c.get(f"{BASE}{pack['acks'][0]['audio_url']}", headers=h)
        check("an ack clip fetches instantly (pre-cached)",
              ac.status_code == 200 and len(ac.content) > 500, f"{len(ac.content)} bytes")

        # ── 3. THE ENGAGEMENT FLOOR ──────────────────────────────────────────
        print("\n3. ENGAGEMENT FLOOR (a real panel never asks six questions into silence)")
        r = c.post(f"{BASE}/session/start", json={**BASE_CFG, "difficulty": "Realistic"}, headers=h)
        sid2 = r.json()["session_id"]
        c.post(f"{BASE}/session/greeting", json={"session_id": sid2, "voice": "female"}, headers=h)

        def skip(session_id):
            rr = c.post(f"{BASE}/session/turn",
                        json={"session_id": session_id, "message": "", "timeout": "skip",
                              "voice": "female"}, headers=h)
            rr.raise_for_status()
            return rr.json()

        t1 = skip(sid2)
        check("silence #1 -> a normal question, no fuss",
              t1["question_kind"] == "question", t1["reply"][:60])

        t2 = skip(sid2)
        check("silence #2 -> THE CHECK-IN (the question march breaks)",
              t2["question_kind"] == "checkin", t2["reply"][:90])
        check("...and it carries its own 45s clock", t2["checkin_seconds"] == 45)

        t3 = skip(sid2)
        check("silence #3 -> a courteous EARLY WRAP",
              t3["state"]["next_action"] == "readout", t3["reply"][:90])
        check("...and the wrap is persisted (a refresh can't dodge it)",
              c.get(f"{BASE}/session/{sid2}/state", headers=h).json()["early_wrap_reason"] == "disengaged")

        # The reset: any response at all puts the interview back on the rails.
        r = c.post(f"{BASE}/session/start", json={**BASE_CFG, "difficulty": "Realistic"}, headers=h)
        sid3 = r.json()["session_id"]
        c.post(f"{BASE}/session/greeting", json={"session_id": sid3, "voice": "female"}, headers=h)
        skip(sid3)
        ck = skip(sid3)
        check("a blank session reaches the check-in in two silences",
              ck["question_kind"] == "checkin")
        yes = c.post(f"{BASE}/session/turn",
                     json={"session_id": sid3, "message": "yes", "voice": "female"}, headers=h).json()
        check("a bare 'yes' RESETS it — the interview simply resumes",
              yes["question_kind"] == "question" and yes["state"]["next_action"] != "readout",
              yes["reply"][:70])

        # ── 4. CRITICAL ──────────────────────────────────────────────────────
        print("\n4. CRITICAL (the pressure panel)")
        r = c.post(f"{BASE}/session/start", json={**BASE_CFG, "difficulty": "Critical"}, headers=h)
        r.raise_for_status()
        sid4 = r.json()["session_id"]
        gc = c.post(f"{BASE}/session/greeting",
                    json={"session_id": sid4, "voice": "female"}, headers=h).json()
        check("a Critical session starts", bool(sid4))
        check("the greeting carries the 'critical' register (the face goes intense)",
              gc["tone"] == "critical", gc["tone"])
        print(f"        opening: {gc['greeting'][:120]}...")

        turn = c.post(f"{BASE}/session/turn", json={
            "session_id": sid4, "voice": "female",
            "message": ("We'd use a logistic regression on the bureau score and DPD buckets. "
                        "Our model gets about 85% accuracy which is pretty good for this book."),
        }, headers=h)
        turn.raise_for_status()
        tb = turn.json()
        check("a Critical turn stays in the critical register", tb["tone"] == "critical", tb["tone"])
        print(f"\n        --- CRITICAL SAMPLE EXCHANGE ---")
        print(f"        Q: {gc['greeting'][:150]}")
        print(f"        A: We'd use a logistic regression on the bureau score and DPD buckets.")
        print(f"           Our model gets about 85% accuracy which is pretty good for this book.")
        print(f"        CHALLENGE: {tb['reply']}")

    print("\n" + ("ALL PASS" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.ConnectError:
        print(f"BACKEND NOT REACHABLE at {BASE} — start it first:")
        print("  cd backend && py -m uvicorn app.main:app --port 8000")
        raise SystemExit(2)
