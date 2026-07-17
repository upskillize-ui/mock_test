#!/usr/bin/env python3
"""QA sweep — dump the setup/lobby DOM so the driver can use real selectors
instead of guesses. Discovery only; writes nothing to the product."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import make_dev_token as mdt  # noqa: E402
from app.dev_auth import build_dev_token  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

env = mdt.load_env(mdt.ENV_PATH)
tok, _ = build_dev_token(env["JWT_SECRET"], sub="qa-sweep-1", name="QA Sweep",
                         email="qa@upskillize.local", days=1,
                         audience=env.get("JWT_AUDIENCE", ""),
                         issuer=env.get("JWT_ISSUER", ""))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=[
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    pg = b.new_page()
    pg.add_init_script(f'localStorage.setItem("upskillize_token", {json.dumps(tok)});')
    pg.goto("http://localhost:5173", wait_until="networkidle")
    pg.wait_for_timeout(2500)
    print("URL:", pg.url, "| title:", pg.title())
    print("\n=== visible text ===")
    print((pg.inner_text("body") or "")[:2500])
    print("\n=== interactive elements ===")
    for el in pg.query_selector_all("button, input, select, textarea, [role=button]"):
        try:
            if not el.is_visible():
                continue
            print(json.dumps({
                "tag": el.evaluate("e=>e.tagName"),
                "type": el.get_attribute("type"),
                "name": el.get_attribute("name"),
                "placeholder": el.get_attribute("placeholder"),
                "aria": el.get_attribute("aria-label"),
                "text": (el.inner_text() or "").strip()[:60],
            }))
        except Exception:
            pass
    b.close()
