#!/usr/bin/env python3
"""QA sweep — is the debrief 502 a max_tokens truncation? Ask the API, don't infer.

Replays the EXACT debrief request /session/end makes for a real stuck session, but
reads `stop_reason` and `usage` off the raw response — which the product code
discards. Then re-runs the same request with a larger cap to see whether the JSON
completes. Read-only: stores nothing, touches no product code.

    python tests/qa_sweep/probe_debrief_cap.py <session_id>
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
from app.config import settings  # noqa: E402
from app import db as appdb  # noqa: E402
from app.claude_client import _headers, _system_block  # noqa: E402
from app.main import _load_debrief_messages, _session_to_cfg  # noqa: E402
from sqlalchemy import text as sqltext  # noqa: E402
from app.prompts import build_system_prompt, debrief_instruction  # noqa: E402

EV = Path(__file__).resolve().parent / "evidence"
EV.mkdir(exist_ok=True)


async def probe(session_id: str, max_tokens: int) -> dict:
    with appdb.db_session() as db:
        row = db.execute(sqltext("SELECT * FROM vyom_sessions WHERE id=:i"),
                         {"i": session_id}).mappings().first()
        cfg = _session_to_cfg(dict(row))
        messages, _ = _load_debrief_messages(db, session_id)
    messages.append({"role": "user", "content": debrief_instruction(cfg)})
    payload = {
        "model": settings.MODEL_DEBRIEF,
        "max_tokens": max_tokens,
        "system": _system_block(build_system_prompt(cfg, ""), ""),
        "messages": messages,
    }
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(settings.ANTHROPIC_URL, headers=_headers(), json=payload)
    j = r.json()
    text = "".join(b.get("text", "") for b in (j.get("content") or []))
    cleaned = text.replace("```json", "").replace("```", "").strip()
    s, e = cleaned.find("{"), cleaned.rfind("}")
    parse_ok, err = False, None
    if s != -1 and e != -1:
        try:
            json.loads(cleaned[s:e + 1])
            parse_ok = True
        except json.JSONDecodeError as ex:
            err = str(ex)
    out = {
        "max_tokens": max_tokens,
        "stop_reason": j.get("stop_reason"),
        "output_tokens": (j.get("usage") or {}).get("output_tokens"),
        "input_tokens": (j.get("usage") or {}).get("input_tokens"),
        "raw_chars": len(text),
        "json_parses": parse_ok,
        "parse_error": err,
        "tail": text[-90:].replace("\n", "\\n"),
    }
    print(json.dumps({k: v for k, v in out.items() if k != "tail"}, indent=2))
    print(f"  tail: ...{out['tail']}")
    return out


async def main():
    sid = sys.argv[1]
    results = []
    for cap in (2500, 2500, 4000):
        print(f"\n=== debrief probe: max_tokens={cap} ===")
        results.append(await probe(sid, cap))
    (EV / "debrief_cap_probe.json").write_text(
        json.dumps({"session_id": sid, "probes": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
