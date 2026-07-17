#!/usr/bin/env python3
"""QA sweep — retry /session/end until it succeeds, then verify the RECORD.

The readout is a render; the debrief row is the record. This finishes each driven
session (counting how many billed attempts the readout costs), then asserts the
row-level contract: mode recorded, benchmark non-null, weights_version non-null,
history row correct.

    python tests/qa_sweep/finish_and_verify.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import httpx  # noqa: E402
import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402

EV = Path(__file__).resolve().parent / "evidence"
env = mdt.load_env(mdt.ENV_PATH)
tok, _ = build_dev_token(env["JWT_SECRET"], sub="qa-sweep-1", name="QA Sweep",
                         email="qa@upskillize.local", days=1,
                         audience=env.get("JWT_AUDIENCE", ""),
                         issuer=env.get("JWT_ISSUER", ""))
c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=180,
                 headers={"Authorization": f"Bearer {tok}"})

out = {}
for mode in ("TEXT", "AUDIO", "VIDEO"):
    f = EV / f"api_{mode}.json"
    if not f.exists():
        continue
    sid = json.loads(f.read_text()).get("session_id")
    if not sid:
        continue
    attempts, readout = [], None
    for i in range(6):
        r = c.post("/session/end", json={"session_id": sid})
        attempts.append(r.status_code)
        if r.status_code == 200:
            readout = r.json()
            break
    out[mode] = {"session_id": sid, "end_attempts": attempts,
                 "billed_failures_before_readout": attempts.count(502)}
    print(f"{mode}: end attempts={attempts}")
    if readout:
        (EV / f"readout_{mode}.json").write_text(json.dumps(readout, indent=2))
        # ONE document? The readout is a single render with all its blocks present.
        blocks = {k: (k in readout and readout[k] not in (None, {}, []))
                  for k in ("overall_band", "round_bands", "strengths", "gaps",
                            "perAnswerScores", "delivery", "professional_presence",
                            "profile", "benchmark", "weights_version")}
        out[mode]["readout_blocks_present"] = blocks
        out[mode]["profile"] = readout.get("profile")
        out[mode]["delivery"] = readout.get("delivery")
        out[mode]["benchmark"] = readout.get("benchmark")
        out[mode]["weights_version"] = readout.get("weights_version")

# The record, straight from the DB.
from app import db as appdb  # noqa: E402
from sqlalchemy import text  # noqa: E402

with appdb.db_session() as s:
    for mode, d in out.items():
        sid = d["session_id"]
        row = s.execute(text(
            "SELECT session_mode, mode, camera_at_join, status FROM vyom_sessions "
            "WHERE id=:i"), {"i": sid}).mappings().first()
        dbr = s.execute(text(
            "SELECT benchmark, benchmark_uncapped, weights_version, gated_band, scored,"
            " substantive_answers FROM vyom_debriefs WHERE session_id=:i"),
            {"i": sid}).mappings().first()
        d["db_session"] = dict(row) if row else None
        d["db_debrief"] = dict(dbr) if dbr else None
        d["contract"] = {
            "mode recorded": (row or {}).get("session_mode") == mode,
            "benchmark non-null": (dbr or {}).get("benchmark") is not None,
            "weights_version non-null": (dbr or {}).get("weights_version") is not None,
            "status completed": (row or {}).get("status") == "completed",
        }

h = c.get("/user/history", params={"limit": 10})
hist = h.json() if h.status_code == 200 else {"status": h.status_code}
sessions = {s_["session_id"]: s_ for s_ in (hist.get("sessions") or [])
            if isinstance(s_, dict) and "session_id" in s_}
for mode, d in out.items():
    d["history_row"] = sessions.get(d["session_id"], "MISSING FROM /user/history")

print(json.dumps(out, indent=2, default=str))
(EV / "completion.json").write_text(json.dumps(
    {"per_mode": out, "history_raw": hist}, indent=2, default=str))
