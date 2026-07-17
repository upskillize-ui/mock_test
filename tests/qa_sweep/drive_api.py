#!/usr/bin/env python3
"""QA sweep — drives REAL sessions against the RUNNING backend, one per mode.

TEST-ONLY harness. Touches no product code. Proves the MODE contract cell by cell
with recorded evidence instead of reading the source and hoping.

    python tests/qa_sweep/drive_api.py                 # all three modes
    python tests/qa_sweep/drive_api.py --mode TEXT

Writes evidence to tests/qa_sweep/evidence/api_<MODE>.json and prints PASS/FAIL
per contract cell. Not named test_* and lives outside backend/tests, so pytest
never collects it (it needs a live server and spends real vendor money).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402

BASE = "http://127.0.0.1:8000"
EVIDENCE = Path(__file__).resolve().parent / "evidence"
EVIDENCE.mkdir(exist_ok=True)

ANSWERS = [
    "Sure. I'm a final-year computer science student and I've spent the last year "
    "working on data pipelines, mostly in Python and SQL. Last semester I built a "
    "dashboard that tracked campus energy use across twelve buildings.",
    "The hardest part was the data quality. Meter readings arrived with gaps and "
    "duplicate timestamps, so I wrote a reconciliation step that flagged anomalies "
    "instead of silently dropping them. That cut bad rows by about eighty percent.",
    "I'd start by asking what decision the number is meant to support. If nobody can "
    "answer that, the metric is decoration. Then I'd check the denominator, because "
    "that's where most misleading percentages hide.",
    "I once shipped a query that double-counted refunds. Finance caught it, not me. "
    "I wrote a regression test for it the same day and started reviewing my own joins "
    "against a known-total check before shipping.",
    "What does the first ninety days look like for someone in this seat, and how would "
    "you know at the end of it whether the hire was a good one?",
    "In my last internship I disagreed with my manager about caching a report. I pulled "
    "the query logs, showed that the underlying table only changed twice a day, and we "
    "settled it on the numbers rather than on seniority.",
    "I'd segment by cohort first. A blended retention curve hides the fact that the "
    "January cohort might be churning while March looks healthy. Then I'd look at the "
    "second-week drop, because that's usually onboarding rather than product.",
    "Honestly, I don't know that one. My instinct would be to look at how the index is "
    "being used before adding another, but I'd want to check the query plan rather than "
    "guess in the room.",
    "I'd rather be told directly. In my project reviews the feedback that actually "
    "changed how I work was the blunt kind — being told my charts were pretty and "
    "unreadable made me rebuild the whole dashboard.",
    "I read the engineering blog and the piece on your delivery-time model. The part "
    "that stuck with me was that you optimise for variance, not just the mean, because "
    "a late order hurts more than an early one helps.",
    "My weakness is that I go deep before I go wide — I'll perfect one query while the "
    "wider question is still open. I've started time-boxing the first pass to get to an "
    "answer, then refining it.",
    "I'd measure success by whether the team stopped asking for the report manually. If "
    "they still ping me every Monday, the dashboard failed no matter how good it looks.",
    "That's a fair challenge. I think the risk with my approach is that flagging "
    "anomalies creates a queue nobody works. So I'd pair it with a threshold that "
    "auto-escalates anything above two percent of revenue.",
]


def token() -> str:
    env = mdt.load_env(mdt.ENV_PATH)
    tok, _ = build_dev_token(
        env["JWT_SECRET"], sub="qa-sweep-1", name="QA Sweep",
        email="qa@upskillize.local", days=1,
        audience=env.get("JWT_AUDIENCE", ""), issuer=env.get("JWT_ISSUER", ""),
    )
    return tok


class Drive:
    def __init__(self, mode: str):
        self.mode = mode
        self.ev = {"mode": mode, "checks": [], "timeline": [], "raw": {}}
        self.c = httpx.Client(
            base_url=BASE, timeout=180.0,
            headers={"Authorization": f"Bearer {token()}"},
        )

    def check(self, name, passed, detail):
        self.ev["checks"].append(
            {"cell": name, "status": "PASS" if passed else "FAIL", "evidence": detail})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}\n         {detail}")

    def log(self, event, **kw):
        self.ev["timeline"].append({"t": round(time.time() - self.t0, 2), "event": event, **kw})

    def post(self, path, body):
        r = self.c.post(path, json=body)
        return r

    def run(self):
        self.t0 = time.time()
        print(f"\n=== driving {self.mode} ===")

        # 1. START
        r = self.post("/session/start", {
            "role": "Data Analyst", "level": "Fresher", "company": "Zomato",
            "duration_min": 20, "difficulty": "Realistic", "mode": "interview",
            "session_mode": self.mode, "round": "full", "voice": "female",
            "camera_at_join": self.mode == "VIDEO",
        })
        if r.status_code != 200:
            print(f"  START FAILED {r.status_code}: {r.text[:400]}")
            self.ev["raw"]["start_error"] = {"status": r.status_code, "body": r.text[:2000]}
            return self.ev
        start = r.json()
        sid = start["session_id"]
        self.ev["session_id"] = sid
        self.ev["raw"]["start"] = start
        self.log("start", session_id=sid)
        print(f"  session_id={sid}  stt_available={start.get('stt_available')}")

        self.check(
            "start: stt_available reflects mode (TEXT must not advertise STT)",
            not (self.mode == "TEXT" and start.get("stt_available") is True),
            f"session_mode={self.mode} -> stt_available={start.get('stt_available')} "
            f"(server computes this from STT_ENABLED and VOICE_ENABLED only)",
        )

        # 2. GREETING — the audio cell
        g = self.post("/session/greeting", {"session_id": sid, "voice": "female"}).json()
        self.ev["raw"]["greeting"] = g
        segs = g.get("audio_segments") or []
        urls = [s.get("audio_url") for s in segs]
        self.log("greeting", segments=len(segs), audio_urls=urls)
        print(f"  greeting: {(g.get('greeting') or '')[:90]!r}")
        if self.mode == "TEXT":
            self.check("TEXT: greeting returns zero audio bytes",
                       all(u is None for u in urls),
                       f"{len(segs)} segments, audio_urls={urls}")
        else:
            self.check(f"{self.mode}: greeting returns real audio bytes",
                       any(u for u in urls),
                       f"{len(segs)} segments, first audio_url={urls[0] if urls else None}")

        # 3. /session/speech — can a client BUY audio it should not have?
        sp = self.post("/session/speech",
                       {"session_id": sid, "voice": "female", "from_index": 0})
        spj = sp.json() if sp.status_code == 200 else {"status": sp.status_code}
        self.ev["raw"]["speech"] = spj
        spurls = [s.get("audio_url") for s in (spj.get("segments") or [])]
        if self.mode == "TEXT":
            self.check("TEXT: /session/speech refuses to synthesize even when asked",
                       all(u is None for u in spurls),
                       f"POST /session/speech from_index=0 -> segments={spurls}")
        else:
            self.check(f"{self.mode}: /session/speech returns audio",
                       any(u for u in spurls) or not spurls,
                       f"segments={spurls}")

        # 4. audio bytes are REAL — fetch one and measure it (server/vendor layer)
        first = next((u for u in urls + spurls if u), None)
        if first:
            a = self.c.get(first)
            body = a.content
            self.check(f"{self.mode}: audio URL serves real bytes (vendor layer)",
                       a.status_code == 200 and len(body) > 1000,
                       f"GET {first} -> {a.status_code}, {len(body)} bytes, "
                       f"content-type={a.headers.get('content-type')}, "
                       f"magic={body[:4].hex()}")
            self.ev["raw"]["audio_probe"] = {
                "url": first, "status": a.status_code, "bytes": len(body),
                "content_type": a.headers.get("content-type"), "magic": body[:4].hex()}
        elif self.mode == "TEXT":
            self.ev["raw"]["audio_probe"] = "no audio offered (correct for TEXT)"

        # 5. /session/clips — the un-gated shared TTS path
        cl = self.c.get("/session/clips", params={"voice": "female"})
        clj = cl.json() if cl.status_code == 200 else {"status": cl.status_code}
        n_clips = len(clj.get("acks") or []) + len(clj.get("backchannels") or [])
        self.ev["raw"]["clips"] = {"status": cl.status_code, "count": n_clips,
                                   "sample": (clj.get("acks") or [])[:2]}
        if self.mode == "TEXT":
            self.check("TEXT: /session/clips serves no synthesized audio to a TEXT client",
                       n_clips == 0,
                       f"GET /session/clips?voice=female -> {cl.status_code}, "
                       f"{n_clips} clips served (endpoint takes no session_id, so it "
                       f"cannot know the caller is TEXT)")

        # 6. STT gate — does a TEXT session get to spend Sarvam STT?
        # Probe twice: before consent (what a fresh TEXT student is), and after
        # consent (what a student who ever used voice in ANY session is, since
        # consent is per-user and durable). The second probe is the real test of
        # whether MODE gates STT, or whether only the consent wall was standing.
        fake = b"\x1a\x45\xdf\xa3" + b"\x00" * 2048  # webm magic + filler

        def stt_probe(label):
            st = self.c.post("/session/stt",
                             data={"session_id": sid, "duration_seconds": "3.0"},
                             files={"audio": ("a.webm", fake, "audio/webm")})
            self.ev["raw"][f"stt_{label}"] = {"status": st.status_code,
                                              "body": st.text[:300]}
            self.log("stt_probe", label=label, status=st.status_code)
            return st

        st1 = stt_probe("before_consent")
        cs = self.post("/consent", {"consent_type": "voice_recording",
                                    "copy_version": "v0-draft", "session_id": sid})
        self.ev["raw"]["consent"] = {"status": cs.status_code, "body": cs.text[:200]}
        st2 = stt_probe("after_consent")
        if self.mode == "TEXT":
            # 403 = consent wall (not a mode gate). 404 = feature off. Anything that
            # reaches the vendor (200/5xx/413/429) means TEXT can spend Sarvam STT.
            self.check(
                "TEXT: /session/stt is refused ON MODE, not merely on consent",
                st2.status_code == 404 or (st2.status_code == 403
                                           and cs.status_code != 200),
                f"before consent -> {st1.status_code} {st1.text[:90]!r}; "
                f"POST /consent -> {cs.status_code}; after consent -> "
                f"{st2.status_code} {st2.text[:120]!r}  (a non-403/404 here means the "
                f"only thing stopping a TEXT session from spending Sarvam STT was the "
                f"consent wall, which is per-user and durable)")

        # 7. Delivery metrics provenance — can TEXT fabricate a Delivery Profile?
        # (sent on the first turn below)

        # 8. TURNS — a full session
        state = self.c.get(f"/session/{sid}/state").json()
        self.ev["raw"]["state_initial"] = state
        cap = state.get("answer_cap") or 20
        i = 0
        last_answer_id = None
        while i < min(len(ANSWERS), cap):
            # The server refuses the next turn until the previous answer is rated
            # (409). A real client rates via the confidence pills; do the same.
            if last_answer_id is not None:
                rr = self.post("/session/turn/rating", {
                    "session_id": sid, "answer_id": last_answer_id, "rating": 4})
                self.log("rating", answer_id=last_answer_id, status=rr.status_code)

            body = {"session_id": sid, "message": ANSWERS[i % len(ANSWERS)],
                    "voice": "female"}
            if i == 0 and self.mode == "TEXT":
                # provenance probe: a typed answer claiming voice delivery metrics
                body["delivery_metrics"] = {
                    "wpm": 155, "filler_count": 9, "filler_rate": 4.2,
                    "longest_pause_ms": 1800, "speaking_seconds": 42.0,
                }
            t = self.post("/session/turn", body)
            if t.status_code != 200:
                self.ev["raw"][f"turn_{i}_error"] = {"status": t.status_code,
                                                     "body": t.text[:400]}
                print(f"  turn {i} -> {t.status_code} {t.text[:200]}")
                break
            tj = t.json()
            last_answer_id = tj.get("answer_id")
            tsegs = tj.get("audio_segments") or []
            turls = [s.get("audio_url") for s in tsegs]
            self.log("turn", i=i, stage=(tj.get("state") or {}).get("current_stage"),
                     audio_urls=turls, reply=(tj.get("reply") or "")[:120])
            self.ev["raw"].setdefault("turns", []).append({
                "i": i, "reply": tj.get("reply"), "audio_urls": turls,
                "tone": tj.get("tone"), "state": tj.get("state")})
            print(f"  turn {i}: stage={(tj.get('state') or {}).get('current_stage')} "
                  f"reply={(tj.get('reply') or '')[:70]!r}")
            if self.mode == "TEXT" and turls:
                self.check(f"TEXT: turn {i} reply carries no audio",
                           all(u is None for u in turls), f"audio_urls={turls}")
            i += 1
            nxt = (tj.get("state") or {}).get("next_action")
            if nxt in ("end", "wrap"):
                break

        # 9. Persona copy scan — device words in a TEXT transcript
        msgs = self.c.get(f"/session/{sid}/messages").json()
        self.ev["raw"]["messages"] = msgs
        assistant = " ".join(m.get("content") or "" for m in (msgs.get("messages") or [])
                             if m.get("role") == "assistant").lower()
        device_words = [w for w in ("mute", "unmute", "mic", "microphone", "camera",
                                    "speak up", "can you hear", "aloud", "out loud")
                        if w in assistant]
        if self.mode == "TEXT":
            self.check("TEXT: interviewer never mentions mic/mute/camera",
                       not device_words,
                       f"device words found in assistant turns: {device_words or 'none'}")

        # 10. /session/reask mute fork — the spoken 'you're on mute' path
        rk = self.post("/session/reask",
                       {"session_id": sid, "voice": "female", "kind": "mute"})
        rkj = rk.json() if rk.status_code == 200 else {"status": rk.status_code}
        self.ev["raw"]["reask_mute"] = rkj
        if self.mode == "TEXT":
            self.check("TEXT: /session/reask kind=mute is refused",
                       rk.status_code != 200,
                       f"POST /session/reask kind=mute -> {rk.status_code}, "
                       f"reply={(rkj.get('reply') or '')[:140]!r}")

        # 11. END → readout
        e = self.post("/session/end", {"session_id": sid})
        ej = e.json() if e.status_code == 200 else {"status": e.status_code,
                                                    "body": e.text[:400]}
        self.ev["raw"]["end"] = ej
        self.log("end", status=e.status_code)
        print(f"  end -> {e.status_code}")
        self.check("end: readout returned", e.status_code == 200,
                   f"POST /session/end -> {e.status_code}")

        if e.status_code == 200:
            dl = ej.get("delivery") or {}
            self.ev["raw"]["delivery_block"] = dl
            if self.mode == "TEXT":
                self.check(
                    "TEXT: readout carries no Delivery block/voice coaching",
                    not dl or dl.get("enough_data") is None,
                    f"delivery={json.dumps(dl)[:220]}")
        return self.ev


def db_rows(session_ids):
    """Read the debrief + session rows straight from the DB — the readout is a
    render, the row is the record."""
    from app import db as appdb
    out = {}
    with appdb.db_session() as s:
        for mode, sid in session_ids.items():
            if not sid:
                continue
            row = s.execute(appdb.text(
                "SELECT session_mode, mode, camera_at_join, status FROM vyom_sessions "
                "WHERE id=:i"), {"i": sid}).mappings().first()
            dbr = s.execute(appdb.text(
                "SELECT benchmark, benchmark_uncapped, weights_version, gated_band, "
                "scored, substantive_answers FROM vyom_debriefs WHERE session_id=:i"),
                {"i": sid}).mappings().first()
            dm = s.execute(appdb.text(
                "SELECT COUNT(*) c FROM vyom_messages WHERE session_id=:i "
                "AND delivery_metrics IS NOT NULL"), {"i": sid}).scalar()
            out[mode] = {"session": dict(row) if row else None,
                         "debrief": dict(dbr) if dbr else None,
                         "messages_with_delivery_metrics": dm}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="ALL")
    a = ap.parse_args()
    modes = ["TEXT", "AUDIO", "VIDEO"] if a.mode == "ALL" else [a.mode]
    ids = {}
    for m in modes:
        ev = Drive(m).run()
        ids[m] = ev.get("session_id")
        (EVIDENCE / f"api_{m}.json").write_text(json.dumps(ev, indent=2, default=str))
    print("\n=== DB rows (the record, not the render) ===")
    rows = db_rows(ids)
    print(json.dumps(rows, indent=2, default=str))
    (EVIDENCE / "db_rows.json").write_text(json.dumps(rows, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
