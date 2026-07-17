#!/usr/bin/env python3
"""QA-09 — the pre-flight's cream band, measured in both shells at three widths.

The band was ~280px of page background above the dark pre-flight, with History/Settings
floating in it. Root cause was two things stacked:
  1. the header's `padding: "16px 32px 8"` — a UNITLESS length, invalid CSS everywhere
     except zero, so the browser dropped the whole shorthand; and
  2. React reuses that <div> from the `screen === "loading"` branch, which sets
     `padding: "120px 20px"`. The rejected assignment left the loading padding in place —
     120px top + 42px button + 120px bottom = the band, on every screen, because the app
     always boots through "loading".

This measures the DOM rather than eyeballing a screenshot: the header's own height, and
the gap between the header and the dark panel. It runs in BOTH shells the product ships in
— the standalone page and the LMS's same-origin iframe (reproduced by routing a synthetic
host page on the app's own origin, so nothing is added to the repo) — at the three widths
the CSS itself names as the verified band (App.jsx: "verified at 1100 / 1280 / 1920").

    python tests/qa_sweep/probe_preflight_layout.py
    QA_BASE_URL=http://localhost:5174 python tests/qa_sweep/probe_preflight_layout.py

Screenshots go to QA_SHOT_DIR (scratchpad — never git).
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
BASE = os.environ.get("QA_BASE_URL", "http://localhost:5173").rstrip("/")

# The LMS gives the app a viewport of its own. This host page is served from the app's
# ORIGIN via routing, so the iframe is same-origin exactly as in the LMS.
EMBED_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>LMS embed harness</title>
<style>html,body{margin:0;padding:0;height:100%;background:#e9edf2}
 .chrome{height:44px;background:#1f2a3a;color:#fff;font:13px system-ui;display:flex;
   align-items:center;padding:0 16px}
 iframe{display:block;width:100%;height:calc(100% - 44px);border:0}</style></head>
<body><div class="chrome">LMS course shell</div>
<iframe id="app" src="{SRC}" allow="microphone; camera"></iframe></body></html>"""

# The header's own box, and the gap between it and the dark pre-flight panel. A healthy
# header is ~66px (16 + 42 + 8); the bug made it 281.
MEASURE_JS = """() => {
  const kids = [...document.querySelectorAll('#root > *')];
  const header = kids.find(el => el.innerText && el.innerText.includes('Settings')
                                && el.getBoundingClientRect().height > 0);
  const dark = kids.find(el => {
    const bg = getComputedStyle(el).backgroundColor;
    return bg === 'rgb(11, 22, 40)' || bg === 'rgb(10, 18, 32)';
  });
  const hr = header ? header.getBoundingClientRect() : null;
  const dr = dark ? dark.getBoundingClientRect() : null;
  return {
    header_h: hr ? Math.round(hr.height) : null,
    header_pad: header ? getComputedStyle(header).padding : null,
    dark_top: dr ? Math.round(dr.top + window.scrollY) : null,
    page_bg: getComputedStyle(document.body).backgroundColor,
    scroll_h: document.documentElement.scrollHeight,
    client_h: document.documentElement.clientHeight,
  };
}"""


def token():
    env = mdt.load_env(mdt.ENV_PATH)
    t, _ = build_dev_token(env["JWT_SECRET"], sub="qa-layout-1", name="QA Layout",
                           email="ql@upskillize.local", days=1,
                           audience=env.get("JWT_AUDIENCE", ""),
                           issuer=env.get("JWT_ISSUER", ""))
    return t


results = []


def check(name, passed, detail):
    results.append({"cell": name, "status": "PASS" if passed else "FAIL", "evidence": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}\n         {detail}")


def drive_to_preflight(frame, waiter):
    """Setup screen -> pre-flight, inside whichever frame the app lives in.

    `frame` is a page or FrameLocator (for finding elements); `waiter` is the page or
    Frame that actually owns wait_for_timeout / wait_for_selector — a FrameLocator has
    neither, which is the whole reason these are passed separately.
    """
    frame.get_by_role("button", name="Audio", exact=True).first.click()
    waiter.wait_for_timeout(250)
    cb = frame.locator('input[type=checkbox]').first
    if cb.count():
        cb.click(force=True)
        waiter.wait_for_timeout(350)
    frame.get_by_role("button", name="Start Interview").first.click()
    frame.get_by_text("Ready to join?").first.wait_for(timeout=30000)
    waiter.wait_for_timeout(600)


def run(shell, width):
    tag = f"{shell}_{width}"
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        ctx = b.new_context(viewport={"width": width, "height": 900},
                            permissions=["microphone", "camera"])
        pg = ctx.new_page()
        pg.add_init_script(f'localStorage.setItem("upskillize_token", {json.dumps(token())});')

        if shell == "embed":
            # Same-origin host page, served from the app's own origin.
            pg.route(f"{BASE}/__embed_host", lambda r: r.fulfill(
                status=200, content_type="text/html",
                body=EMBED_HTML.replace("{SRC}", BASE + "/")))
            pg.goto(f"{BASE}/__embed_host", wait_until="networkidle")
            pg.wait_for_timeout(1500)
            # Wait for the app's own frame (not the host chrome) to attach.
            app_frame = None
            for _ in range(40):
                app_frame = next((f for f in pg.frames if f != pg.main_frame
                                  and (f.url or "").startswith(BASE)), None)
                if app_frame:
                    break
                pg.wait_for_timeout(250)
            assert app_frame, "app iframe never attached"
            target = pg.frame_locator("#app")
            drive_to_preflight(target, app_frame)
            m = app_frame.evaluate(MEASURE_JS)
        else:
            pg.goto(BASE, wait_until="networkidle")
            pg.wait_for_timeout(1200)
            drive_to_preflight(pg, pg)
            m = pg.evaluate(MEASURE_JS)

        pg.evaluate("window.scrollTo(0,0)")
        shot = SHOTS / f"QA09_{tag}.png"
        pg.screenshot(path=str(shot))
        m.update({"shell": shell, "width": width, "shot": str(shot)})

        # A healthy header is 16 + 42 + 8 = 66px. The bug made it 281 (120+42+120).
        check(f"{shell} @{width}: header is its own size, not the loading screen's",
              m["header_h"] is not None and m["header_h"] <= 80,
              f"header height={m['header_h']}px padding={m['header_pad']} "
              f"(band was 281px / 120px 20px)")
        # The band is the header's own padding, so there is no "gap" between it and the
        # dark panel to measure — they are flush either way, and an assertion on that
        # passes while the band is 280px tall (it did; that check was worthless and is
        # gone). The student-visible second symptom is that the pre-flight SCROLLS: the
        # band pushed total content past the viewport, so "Ready to join?" opened
        # part-scrolled with the join button under the fold.
        overflow = m["scroll_h"] - m["client_h"]
        check(f"{shell} @{width}: the pre-flight fits the viewport (no scroll)",
              overflow <= 2,
              f"content {m['scroll_h']}px vs viewport {m['client_h']}px -> overflow="
              f"{overflow}px | dark panel starts at y={m['dark_top']} | page bg={m['page_bg']}")
        results[-1]["shot"] = str(shot)
        b.close()
    return m


print(f"QA-09 — pre-flight layout, both shells, three widths  (base={BASE})")
measurements = []
for shell in ("standalone", "embed"):
    for width in (1100, 1280, 1920):
        print(f"\n=== {shell} @ {width} ===")
        measurements.append(run(shell, width))

(EV / "preflight_layout.json").write_text(json.dumps(
    {"base": BASE, "measurements": measurements, "checks": results}, indent=2, default=str))
bad = [r for r in results if r["status"] == "FAIL"]
print(f"\n{len(results) - len(bad)}/{len(results)} pass")
print(f"screenshots (not in git): {SHOTS}")
sys.exit(1 if bad else 0)
