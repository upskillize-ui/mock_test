#!/usr/bin/env python3
"""QA sweep — pacing probes that need a hand on the keyboard.

Answers the questions the idle run cannot:
  1. Does TYPING suppress the mute nudge in TEXT? (the suppression rule)
  2. Is the per-question timer chip visible while the student is actively typing?
  3. Does a slow typist get rebuked / escalated?
  4. Cold-start: how long from "Start Interview" to a usable lobby, and from
     "Join" to the first question?
  5. Is the pre-flight role the one the student picked (stale-role suspect)?

    python tests/qa_sweep/probe_pacing.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

EV = Path(__file__).resolve().parent / "evidence"
EV.mkdir(exist_ok=True)
SHOTS = Path(os.environ.get("QA_SHOT_DIR",
                            Path(tempfile.gettempdir()) / "qa_sweep_shots"))
SHOTS.mkdir(parents=True, exist_ok=True)

env = mdt.load_env(mdt.ENV_PATH)
TOK, _ = build_dev_token(env["JWT_SECRET"], sub="qa-pacing-1", name="QA Pacing",
                         email="qap@upskillize.local", days=1,
                         audience=env.get("JWT_AUDIENCE", ""),
                         issuer=env.get("JWT_ISSUER", ""))

SLOW_ANSWER = ("I built a dashboard that tracked campus energy use across twelve "
               "buildings, and the hardest part was reconciling meter gaps.")

out = {}

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=[
        "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
        "--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context(permissions=["microphone", "camera"])
    pg = ctx.new_page()
    pg.add_init_script(f'localStorage.setItem("upskillize_token", {json.dumps(TOK)});')
    reasks = []
    pg.on("response", lambda r: reasks.append(
        {"t": time.time(), "url": r.url.split("8000")[-1], "status": r.status})
        if "/session/reask" in r.url else None)

    pg.goto("http://localhost:5173", wait_until="networkidle")
    pg.wait_for_timeout(1200)

    # Pick a DISTINCT role so the pre-flight's role can be checked for staleness.
    pg.get_by_role("button", name="Text", exact=True).first.click()
    pg.select_option("select", label="Data Analyst")
    pg.wait_for_timeout(200)
    pg.locator('input[type=checkbox]').first.click(force=True)
    pg.wait_for_timeout(300)

    t0 = time.time()
    pg.get_by_role("button", name="Start Interview").first.click()
    pg.wait_for_selector("text=Join interview", timeout=30000)
    out["cold_start_setup_to_lobby_s"] = round(time.time() - t0, 2)

    lobby = pg.inner_text("body")
    out["preflight_role_shown"] = [l for l in lobby.split("\n")
                                   if "Analyst" in l or "Engineer" in l][:3]
    out["preflight_role_matches_choice"] = (
        "Data Analyst" in lobby and "Software Engineer" not in lobby)
    # The "top gap" suspect: is there dead space above the first content?
    out["preflight_first_lines"] = [l for l in lobby.split("\n")[:6]]

    t1 = time.time()
    pg.get_by_role("button", name="Join interview").first.click()
    # First question = the composer exists AND the interviewer has said something
    # substantial (the greeting paragraph landing in the transcript).
    pg.wait_for_selector("textarea", timeout=45000)
    deadline = time.time() + 60
    while time.time() < deadline:
        lines = [l.strip() for l in pg.inner_text("body").split("\n")]
        if any(len(l) > 120 for l in lines):
            break
        pg.wait_for_timeout(500)
    out["join_to_first_question_s"] = round(time.time() - t1, 2)

    # ── 1+2+3: type steadily, like a slow but engaged student ──────────────
    box = pg.locator("textarea").first
    box.click()
    t_type = time.time()
    typed_marks = []
    for i, ch in enumerate(SLOW_ANSWER):
        box.type(ch, delay=0)
        if i % 12 == 0:
            body = pg.inner_text("body")
            typed_marks.append({
                "at_s": round(time.time() - t_type, 1),
                "chars": i,
                "mute_line_present": "on mute" in body.lower(),
                "q_chip_present": "THIS QUESTION" in body,
            })
        pg.wait_for_timeout(320)  # ~ a deliberate typist
    out["while_typing"] = typed_marks
    out["typing_duration_s"] = round(time.time() - t_type, 2)
    out["mute_nudge_while_typing"] = any(m["mute_line_present"] for m in typed_marks)
    out["q_chip_visible_while_typing"] = any(m["q_chip_present"] for m in typed_marks)
    out["reasks_during_typing"] = len(reasks)
    pg.screenshot(path=str(SHOTS / "TEXT_typing.png"), full_page=True)

    body = pg.inner_text("body")
    out["rebuke_while_typing"] = [
        l for l in body.split("\n")
        if any(w in l.lower() for w in ("real panel", "cost them", "stay with me",
                                        "attention", "drifted"))][:3]

    pg.get_by_role("button", name="Send").first.click()
    pg.wait_for_timeout(9000)
    out["after_send_text"] = pg.inner_text("body")[-700:]
    b.close()

print(json.dumps(out, indent=2, default=str)[:2600])
(EV / "pacing.json").write_text(json.dumps(out, indent=2, default=str))
