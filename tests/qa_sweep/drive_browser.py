#!/usr/bin/env python3
"""QA sweep — drives the REAL app in a REAL Chromium, one run per mode.

Instruments the three layers the "audio not working" complaint collapses together,
so each one reports for itself:
  - vendor/server layer: which /session/speech + /session/audio fetches happen, and
    how many bytes come back
  - app layer: does the client construct an Audio element and call .play()
  - permission/autoplay layer: does .play() reject (the "Tap to enable audio" path)
Input side, same treatment: getUserMedia calls (with their exact constraints),
granted/denied, and whether the mic ever opens.

Fake devices are used (--use-fake-device-for-media-stream), so the mic carries a
real signal without a human in the room.

    python tests/qa_sweep/drive_browser.py --mode TEXT
    python tests/qa_sweep/drive_browser.py            # all three
    python tests/qa_sweep/drive_browser.py --mode TEXT --autoplay-blocked

Evidence -> tests/qa_sweep/evidence/browser_<MODE>.json (no screenshots in git;
they go to the scratchpad dir).
"""
import argparse
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
SHOTS = Path(os.environ.get(
    "QA_SHOT_DIR", Path(tempfile.gettempdir()) / "qa_sweep_shots"))
SHOTS.mkdir(parents=True, exist_ok=True)

# Wraps getUserMedia and HTMLMediaElement.play BEFORE any app code runs, so the
# record is what the app actually did, not what we hoped it did.
INSTRUMENT = r"""
window.__qa = { gum: [], play: [], audioCtor: [], errors: [] };
const origGum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = async (c) => {
  const rec = { t: Date.now(), constraints: JSON.parse(JSON.stringify(c || {})),
                stack: (new Error().stack || "").split("\n").slice(2, 5).join(" | ") };
  window.__qa.gum.push(rec);
  try {
    const s = await origGum(c);
    rec.granted = true;
    rec.tracks = s.getTracks().map(t => ({ kind: t.kind, label: t.label }));
    return s;
  } catch (e) { rec.granted = false; rec.error = String(e); throw e; }
};
const OrigAudio = window.Audio;
window.Audio = function (...a) {
  window.__qa.audioCtor.push({ t: Date.now(), src: a[0] || null });
  return new OrigAudio(...a);
};
window.Audio.prototype = OrigAudio.prototype;
const origPlay = HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play = function () {
  const rec = { t: Date.now(), src: String(this.src || "").slice(0, 120),
                tag: this.tagName };
  window.__qa.play.push(rec);
  return origPlay.apply(this, arguments).then(
    () => { rec.result = "played"; },
    (e) => { rec.result = "REJECTED"; rec.error = String(e).slice(0, 160); throw e; });
};
window.addEventListener("error", e => window.__qa.errors.push(String(e.message)));
window.addEventListener("unhandledrejection",
  e => window.__qa.errors.push("unhandledrejection: " + String(e.reason).slice(0, 200)));
"""

DEVICE_WORDS = ["mute", "unmute", "microphone", " mic ", "camera", "speak up",
                "can you hear", "aloud", "out loud", "tap to enable audio",
                "tap to hear"]


def token():
    env = mdt.load_env(mdt.ENV_PATH)
    t, _ = build_dev_token(env["JWT_SECRET"], sub="qa-browser-1", name="QA Browser",
                           email="qab@upskillize.local", days=1,
                           audience=env.get("JWT_AUDIENCE", ""),
                           issuer=env.get("JWT_ISSUER", ""))
    return t


def run(mode, autoplay_blocked=False, idle_seconds=25):
    ev = {"mode": mode, "autoplay_blocked": autoplay_blocked, "checks": [],
          "network": [], "console": [], "screens": []}

    def check(name, passed, detail):
        ev["checks"].append({"cell": name, "status": "PASS" if passed else "FAIL",
                             "evidence": detail})
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}\n         {detail}")

    args = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]
    if autoplay_blocked:
        # The real-world default a student meets on a cold tab.
        args.append("--autoplay-policy=document-user-activation-required")
    else:
        args.append("--autoplay-policy=no-user-gesture-required")

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=args)
        ctx = b.new_context(permissions=["microphone", "camera"])
        pg = ctx.new_page()
        pg.add_init_script(f'localStorage.setItem("upskillize_token", '
                           f'{json.dumps(token())});')
        pg.add_init_script(INSTRUMENT)
        pg.on("console", lambda m: ev["console"].append(f"{m.type}: {m.text[:200]}"))

        def on_resp(r):
            u = r.url
            if any(k in u for k in ("/session/", "/user/", "/consent")):
                rec = {"url": u.replace("http://127.0.0.1:8000", "")
                       .replace("http://localhost:8000", ""),
                       "method": r.request.method, "status": r.status}
                if "/session/audio/" in u:
                    # r.body() is unavailable once the media element consumes the
                    # stream, so size it from the header the server actually sent.
                    try:
                        rec["bytes"] = int(r.header_value("content-length") or 0)
                    except Exception:
                        rec["bytes"] = 0
                ev["network"].append(rec)
        pg.on("response", on_resp)

        print(f"\n=== browser: {mode} (autoplay_blocked={autoplay_blocked}) ===")
        pg.goto("http://localhost:5173", wait_until="networkidle")
        pg.wait_for_timeout(1500)

        # ── setup screen ───────────────────────────────────────────────────
        pg.get_by_role("button", name=mode.capitalize(), exact=True).first.click()
        pg.wait_for_timeout(300)
        cb = pg.locator('input[type=checkbox]').first
        if cb.count():
            cb.click(force=True)
            pg.wait_for_timeout(400)
            # The consent row collapses once accepted, so the checkbox itself is
            # gone; the gate text disappearing is the signal that it took.
            ev["consent_accepted"] = "Please accept" not in pg.inner_text("body")
        ev["screens"].append(str(SHOTS / f"{mode}_1_setup.png"))
        pg.screenshot(path=str(SHOTS / f"{mode}_1_setup.png"), full_page=True)
        pg.get_by_role("button", name="Start Interview").first.click()
        pg.wait_for_timeout(3000)

        # ── pre-flight / lobby ─────────────────────────────────────────────
        lobby_text = pg.inner_text("body")
        ev["lobby_text"] = lobby_text
        pg.screenshot(path=str(SHOTS / f"{mode}_2_lobby.png"), full_page=True)
        ev["screens"].append(str(SHOTS / f"{mode}_2_lobby.png"))
        low = lobby_text.lower()
        # "No microphone needed, so we won't ask for one" is device copy that
        # KEEPS the promise — it names the device only to say it isn't wanted.
        # Scanning for the bare word would score that sentence as a defect, so
        # scan for copy that ASKS for a device instead.
        asking = [w for w in ("allow mic", "allow camera", "enable your mic",
                              "turn on your camera", "mic only", "camera off",
                              "we'll ask", "permission") if w in low]
        ev["lobby_device_controls"] = [
            b.inner_text().strip() for b in pg.locator("button").all()
            if b.is_visible()]
        if mode == "TEXT":
            check("TEXT pre-flight: no device UI/copy that asks for a device",
                  not asking,
                  f"device-request copy: {asking or 'none'} | buttons: "
                  f"{ev['lobby_device_controls']} | reassurance copy present: "
                  f"{'no microphone needed' in low}")
        if mode == "AUDIO":
            check("AUDIO pre-flight: asks MIC ONLY (no camera request/copy)",
                  "camera" not in low,
                  f"camera copy on AUDIO pre-flight: "
                  f"{'PRESENT' if 'camera' in low else 'absent'} | "
                  f"lobby buttons: {[b.inner_text() for b in pg.locator('button').all() if b.is_visible()][:6]}")
        check(f"{mode} pre-flight: DRAFT NOTICE not shown to students",
              "draft notice" not in low,
              f"'DRAFT NOTICE — PENDING LEGAL REVIEW' "
              f"{'VISIBLE' if 'draft notice' in low else 'absent'} on pre-flight")

        # ── join ───────────────────────────────────────────────────────────
        # The lobby is TWO steps for AUDIO/VIDEO: grant the device, THEN join.
        # Clicking "Allow mic & camera" alone leaves the student in the lobby.
        clicks = []
        # "Allow mic" is AUDIO's primary CTA since QA-04; VIDEO keeps "Allow mic & camera".
        for label in ("Allow mic & camera", "Allow mic", "Mic only", "Join interview", "Join"):
            btn = pg.get_by_role("button", name=label, exact=False)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                clicks.append(label)
                pg.wait_for_timeout(2500)
                if "join" in label.lower():
                    break
        ev["join_clicks"] = clicks
        ev["reached_room"] = "Ready to join?" not in pg.inner_text("body")
        print(f"  lobby clicks: {clicks} | reached room: {ev['reached_room']}")
        if not ev["reached_room"]:
            vis = [b.inner_text().strip() for b in pg.locator("button").all()
                   if b.is_visible()]
            ev["lobby_stuck_buttons"] = vis
            print(f"  STILL IN LOBBY — visible buttons: {vis}")
        pg.wait_for_timeout(9000)  # greeting + first question

        gum = pg.evaluate("window.__qa.gum")
        ev["getUserMedia_calls"] = gum
        if mode == "TEXT":
            check("TEXT: zero getUserMedia calls",
                  len(gum) == 0,
                  f"{len(gum)} getUserMedia call(s): "
                  f"{[g['constraints'] for g in gum]}")
        if mode == "AUDIO":
            vid = [g for g in gum if g["constraints"].get("video")]
            check("AUDIO: getUserMedia never requests video",
                  not vid,
                  f"{len(gum)} call(s); with video: {[g['constraints'] for g in vid]}")
        if mode == "VIDEO":
            check("VIDEO: getUserMedia requests mic+camera",
                  any(g["constraints"].get("video") for g in gum)
                  and any(g["constraints"].get("audio") for g in gum),
                  f"constraints: {[g['constraints'] for g in gum]}")

        pg.screenshot(path=str(SHOTS / f"{mode}_3_room.png"), full_page=True)
        ev["screens"].append(str(SHOTS / f"{mode}_3_room.png"))

        # ── idle: the pacing probe. Do not type; watch what she does. ───────
        t_room = pg.evaluate("Date.now()")
        transcript_seen = set()
        nudges = []
        for _ in range(int(idle_seconds / 0.5)):
            pg.wait_for_timeout(500)
            try:
                txt = pg.inner_text("body")
            except Exception:
                break
            for line in txt.split("\n"):
                line = line.strip()
                if len(line) > 25 and line not in transcript_seen:
                    transcript_seen.add(line)
                    low_l = line.lower()
                    if any(w in low_l for w in ("mute", "mic", "hear you", "camera")):
                        nudges.append({
                            "at_s": round((pg.evaluate("Date.now()") - t_room) / 1000, 1),
                            "line": line[:160]})
        ev["idle_seconds_watched"] = idle_seconds
        ev["device_lines_while_idle"] = nudges
        pg.screenshot(path=str(SHOTS / f"{mode}_4_idle.png"), full_page=True)
        ev["screens"].append(str(SHOTS / f"{mode}_4_idle.png"))

        if mode == "TEXT":
            check("TEXT: persona never says mute/mic while student is idle",
                  not nudges,
                  f"device lines during {idle_seconds}s idle: "
                  f"{json.dumps(nudges)[:400]}")

        # ── room UI contract ───────────────────────────────────────────────
        room_text = pg.inner_text("body")
        ev["room_text"] = room_text
        rlow = room_text.lower()
        btns = [b.inner_text().strip() or (b.get_attribute("aria-label") or "")
                for b in pg.locator("button").all() if b.is_visible()]
        ev["room_buttons"] = btns
        if mode == "TEXT":
            check("TEXT: no mic/camera buttons in the room",
                  not any("mic" in x.lower() or "camera" in x.lower() for x in btns),
                  f"visible buttons: {btns}")
            check("TEXT: typing composer present",
                  pg.locator("textarea, input[type=text]").count() > 0,
                  f"composer count: {pg.locator('textarea, input[type=text]').count()}")
            check("TEXT: no 'Tap to enable audio' affordance",
                  "tap to enable audio" not in rlow and "tap to hear" not in rlow,
                  f"audio-unblock chip: "
                  f"{'VISIBLE' if 'tap to' in rlow else 'absent'}")

        # ── audio layers ───────────────────────────────────────────────────
        plays_all = pg.evaluate("window.__qa.play")
        # The silent-WAV autoplay unlock is not speech. Counting it as "TEXT
        # played audio" would be a false defect; it plays 44 bytes of silence.
        plays = [p for p in plays_all
                 if not str(p.get("src", "")).startswith("data:audio/wav;base64,UklGRiQ")]
        ev["silent_unlock_plays"] = len(plays_all) - len(plays)
        ctors = pg.evaluate("window.__qa.audioCtor")
        ev["audio_play_calls"] = plays
        ev["audio_constructed"] = len(ctors)
        speech = [n for n in ev["network"] if "/session/speech" in n["url"]]
        clips = [n for n in ev["network"] if "/session/clips" in n["url"]]
        audio_fetch = [n for n in ev["network"] if "/session/audio/" in n["url"]]
        ev["layers"] = {
            "server_speech_calls": len(speech),
            "clip_pack_calls": len(clips),
            "audio_byte_fetches": len(audio_fetch),
            "audio_bytes_total": sum(n.get("bytes", 0) for n in audio_fetch),
            "audio_elements_constructed": len(ctors),
            "play_attempts": len(plays),
            "play_rejected": len([p for p in plays if p.get("result") == "REJECTED"]),
        }
        print(f"  layers: {json.dumps(ev['layers'])}")

        if mode == "TEXT":
            check("TEXT: zero /session/speech calls",
                  not speech, f"{len(speech)} call(s): {speech}")
            check("TEXT: zero clip-pack fetches",
                  not clips, f"{len(clips)} call(s): {clips}")
            check("TEXT: zero audio bytes fetched",
                  not audio_fetch,
                  f"{len(audio_fetch)} fetch(es), "
                  f"{sum(n.get('bytes', 0) for n in audio_fetch)} bytes")
            check("TEXT: client never plays speech audio",
                  not plays,
                  f"speech play() calls: {json.dumps(plays)[:300] if plays else 'none'} "
                  f"(plus {ev['silent_unlock_plays']} silent-WAV autoplay-unlock "
                  f"play(s), which carry no speech)")
            check("TEXT: no voice-only controls in the room",
                  not any("voice" in x.lower() or "caption" in x.lower()
                          for x in btns),
                  f"visible buttons: {btns}")
        else:
            check(f"{mode} (a) server layer: /session/speech returns audio",
                  bool(audio_fetch) and
                  sum(n.get("bytes", 0) for n in audio_fetch) > 1000,
                  f"{len(audio_fetch)} audio fetch(es), "
                  f"{sum(n.get('bytes', 0) for n in audio_fetch)} bytes total")
            check(f"{mode} (b) app layer: client creates + plays an audio element",
                  bool(plays),
                  f"{len(ctors)} Audio() constructed, {len(plays)} play() call(s)")
            check(f"{mode} (c) permission layer: playback not blocked",
                  not any(p.get("result") == "REJECTED" for p in plays),
                  f"rejected: {[p.get('error') for p in plays if p.get('result') == 'REJECTED'][:2]} | "
                  f"'Tap to enable audio' visible: {'tap to enable audio' in rlow}")

        ev["js_errors"] = pg.evaluate("window.__qa.errors")
        if ev["js_errors"]:
            print(f"  JS errors: {ev['js_errors'][:3]}")
        b.close()

    (EV / f"browser_{mode}{'_blocked' if autoplay_blocked else ''}.json").write_text(
        json.dumps(ev, indent=2, default=str))
    return ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="ALL")
    ap.add_argument("--autoplay-blocked", action="store_true")
    ap.add_argument("--idle", type=int, default=25)
    a = ap.parse_args()
    modes = ["TEXT", "AUDIO", "VIDEO"] if a.mode == "ALL" else [a.mode]
    for m in modes:
        try:
            run(m, autoplay_blocked=a.autoplay_blocked, idle_seconds=a.idle)
        except Exception as e:
            print(f"  DRIVE ERROR ({m}): {type(e).__name__}: {e}")
    print(f"\nscreenshots (not in git): {SHOTS}")


if __name__ == "__main__":
    main()
