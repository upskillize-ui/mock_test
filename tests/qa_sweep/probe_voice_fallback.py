#!/usr/bin/env python3
"""QA-05 — drive the voice-failure path with a DENIED microphone.

The sweep could only flag this one by inspection: our fake mic never failed, so the
rescue path never ran. This drives it for real. The browser is launched WITHOUT
--use-fake-ui-for-media-stream and with no microphone permission, so getUserMedia
rejects exactly as it does for a student whose mic is broken, blocked, or claimed by
another app. That lands in App.jsx's `catch { voiceFallback(); return; }`.

Before the fix, voiceFallback called setTypeOpen() — an identifier with one reference
and no definition anywhere — so the rescue threw a ReferenceError and the student got a
dead end. After it, they get a toast and the composer.

    python tests/qa_sweep/probe_voice_fallback.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

EV = Path(__file__).resolve().parent / "evidence"
EV.mkdir(exist_ok=True)
SHOTS = Path(os.environ.get("QA_SHOT_DIR", Path(tempfile.gettempdir()) / "qa_sweep_shots"))
SHOTS.mkdir(parents=True, exist_ok=True)

env = mdt.load_env(mdt.ENV_PATH)
TOK, _ = build_dev_token(env["JWT_SECRET"], sub="qa-fallback-1", name="QA Fallback",
                         email="qf@upskillize.local", days=1,
                         audience=env.get("JWT_AUDIENCE", ""),
                         issuer=env.get("JWT_ISSUER", ""))

INSTRUMENT = r"""
window.__qa = { errors: [], gum: [] };
window.addEventListener("error", e => window.__qa.errors.push(String(e.message)));
window.addEventListener("unhandledrejection",
  e => window.__qa.errors.push("unhandledrejection: " + String(e.reason).slice(0, 200)));
const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async (c) => {
  const rec = { constraints: JSON.parse(JSON.stringify(c || {})) };
  window.__qa.gum.push(rec);
  try { const s = await orig(c); rec.granted = true; return s; }
  catch (e) { rec.granted = false; rec.error = String(e).slice(0, 80); throw e; }
};
"""

out = {"checks": []}


def check(name, passed, detail):
    out["checks"].append({"cell": name, "status": "PASS" if passed else "FAIL",
                          "evidence": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}\n         {detail}")


with sync_playwright() as p:
    # No --use-fake-ui-for-media-stream: the prompt is NOT auto-accepted.
    b = p.chromium.launch(headless=True, args=[
        "--use-fake-device-for-media-stream",
        "--autoplay-policy=no-user-gesture-required"])
    ctx = b.new_context()          # no permissions granted -> getUserMedia rejects
    ctx.clear_permissions()
    pg = ctx.new_page()
    console = []
    pg.on("console", lambda m: console.append(f"{m.type}: {m.text[:200]}"))
    pg.add_init_script(f'localStorage.setItem("upskillize_token", {json.dumps(TOK)});')
    pg.add_init_script(INSTRUMENT)

    pg.goto("http://localhost:5173", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    pg.get_by_role("button", name="Audio", exact=True).first.click()
    pg.locator('input[type=checkbox]').first.click(force=True)
    pg.wait_for_timeout(300)
    pg.get_by_role("button", name="Start Interview").first.click()
    pg.wait_for_selector("text=Ready to join?", timeout=30000)

    # The student allows the mic; the browser refuses. This is the whole point.
    pg.get_by_role("button", name="Allow mic", exact=False).first.click()
    pg.wait_for_timeout(2500)
    lobby = pg.inner_text("body")
    out["lobby_notice_after_denial"] = [l.strip() for l in lobby.split("\n")
                                        if "mic" in l.lower() and "access" in l.lower()][:2]
    check("QA-05: a denied mic never hard-blocks the lobby",
          "Join interview" in lobby,
          f"lobby still offers a way in; notice={out['lobby_notice_after_denial']}")

    pg.get_by_role("button", name="Join interview").first.click()
    # In AUDIO the composer lives in the collapsed chat panel, so there is no textarea to
    # wait on yet — that is the point of the rescue. Wait for the interviewer to speak.
    pg.wait_for_selector("text=Ready to join?", state="detached", timeout=45000)
    deadline = pg.evaluate("Date.now()") + 60000
    while pg.evaluate("Date.now()") < deadline:
        if any(len(l.strip()) > 120 for l in pg.inner_text("body").split("\n")):
            break
        pg.wait_for_timeout(500)
    pg.wait_for_timeout(2000)
    out["composer_before_failure"] = pg.locator("textarea").count()

    # In the room with a dead mic. Tap it — this is the rescue path.
    errors_before = pg.evaluate("window.__qa.errors")
    mic = pg.get_by_role("button", name="Unmute microphone", exact=False)
    out["mic_button_present"] = bool(mic.count())
    if mic.count():
        mic.first.click()
        pg.wait_for_timeout(2000)
        # Unmuting is gated on voice consent before it ever reaches getUserMedia, so the
        # modal stands between the tap and the failure path. Accept it as a student would.
        accept = pg.locator("button", has_text="record").filter(has_text="Allow")
        out["consent_modal_shown"] = bool(accept.count())
        if accept.count():
            accept.first.click()
            pg.wait_for_timeout(4000)
        # Consent granted, mic still dead: this second tap is the one that reaches
        # getUserMedia and rejects.
        mic2 = pg.get_by_role("button", name="Unmute microphone", exact=False)
        if mic2.count() and mic2.first.is_visible():
            mic2.first.click()
            # The toast self-dismisses after 4s, so poll for it rather than reading the
            # body once and racing it — a disappeared toast is not an absent one.
            out["toast_seen"] = False
            for _ in range(16):
                pg.wait_for_timeout(250)
                if "voice input unavailable" in pg.inner_text("body").lower():
                    out["toast_seen"] = True
                    break
            pg.wait_for_timeout(1500)

    body = pg.inner_text("body")
    errors = pg.evaluate("window.__qa.errors")
    gum = pg.evaluate("window.__qa.gum")
    out["js_errors"] = errors
    out["getUserMedia"] = gum
    out["console_errors"] = [c for c in console if c.startswith("error")]
    pg.screenshot(path=str(SHOTS / "AUDIO_mic_denied.png"), full_page=True)

    denied = [g for g in gum if g.get("granted") is False]
    check("QA-05: the mic really was denied (the failure path actually ran)",
          bool(denied),
          f"{len(gum)} getUserMedia call(s), {len(denied)} rejected: "
          f"{[g.get('error') for g in denied][:2]}")

    ref_errors = [e for e in errors + out["console_errors"]
                  if "setTypeOpen" in e or "is not defined" in e]
    check("QA-05: the rescue does not throw ReferenceError",
          not ref_errors,
          f"errors mentioning an undefined identifier: {ref_errors or 'none'}")

    # The substantive rescue is the COMPOSER: the toast alone is a message about a dead
    # end, not a way out of one. The composer was closed before the failure (AUDIO keeps
    # it in a collapsed panel), so its presence here is the fallback having run.
    composer_after = pg.locator("textarea").count()
    check("QA-05: the voice failure hands the student the composer",
          composer_after > 0,
          f"composer before failure: {out.get('composer_before_failure')} -> after: "
          f"{composer_after} | toast seen: {out.get('toast_seen')}")

    out["errors_before_tap"] = errors_before
    b.close()

(EV / "voice_fallback.json").write_text(json.dumps(out, indent=2, default=str))
print(f"\nevidence: {EV / 'voice_fallback.json'}")
