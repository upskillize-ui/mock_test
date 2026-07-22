"""Golden-transcript band stability — is the rubric an instrument yet?

THE QUESTION THIS ANSWERS
A band (Not Ready / Building / Interview-Ready / Offer-Ready) is a high-stakes label a
placement cell will read. An instrument gives the same answer to the same input; a
generator gives a different one each run. This harness feeds FIXED reference transcripts
through the REAL debrief path (build_system_prompt -> debrief_instruction -> Claude ->
band_for) N times each, and reports whether the band held still.

PASS  = every run of a transcript lands on the same band.
DRIFT = the band flipped between runs. A drifting band is not a tuning problem — it means
        the rubric + model combination is not yet reliable enough to print verdicts, and
        that has to be fixed (tighter rubric anchors, lower temperature, or a model pin)
        before any launch-quality claim.

USAGE (from vyom_build/, with backend deps installed and ANTHROPIC_API_KEY set):
    python scripts/band_stability.py            # 3 transcripts x 5 runs (~15 calls)
    python scripts/band_stability.py --runs 3   # cheaper smoke
Exit code 0 on PASS for all transcripts, 1 on any drift — CI-friendly.

Cost note: each run is one debrief-sized call (max_tokens=8000). Keep --runs modest.
No session, no DB, no vyom_ tables — this never touches production data.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app import stages  # noqa: E402
from app.claude_client import call_claude  # noqa: E402
from app.config import settings  # noqa: E402
from app.prompts import build_system_prompt, debrief_instruction  # noqa: E402

# ── The golden transcripts ───────────────────────────────────────────────────
# Deliberately synthetic (no real student data), deliberately spread across the band
# ladder. Each is (label, expected_band_zone, cfg, messages). The expectation is a ZONE
# (set of acceptable bands), because the point here is STABILITY run-to-run, not pinning
# the exact band — but a result far outside the zone is flagged too.

_BASE_CFG = {
    "name": "Golden Student", "role": "Software Engineer (SDE)", "level": "Fresher",
    "company": "", "duration_min": 20, "difficulty": "Realistic", "mode": "interview",
    "session_mode": "AUDIO", "round": "full", "round_label": "", "round_detail": "",
    "focus": [], "intro": "", "interviewer_identity": "steady, collegial, opens on trade-offs",
    "interviewer_name": "Meera",
}


def _t(*turns):
    """Alternate assistant/user turns; tag answers like _load_debrief_messages does."""
    out, aid = [], 100
    for i, text in enumerate(turns):
        if i % 2 == 0:
            out.append({"role": "assistant", "content": text})
        else:
            out.append({"role": "user", "content": f"[answer #{aid}] {text}"})
            aid += 1
    return out


GOLDENS = [
    (
        "strong_fresher",
        {"Interview-Ready", "Offer-Ready"},
        _t(
            "Tell me about a project you own end to end.",
            "I built the attendance service for my college fest app — Node and MySQL. The hard call was "
            "sessions versus JWTs; I picked JWTs so the check-in desks could work offline and sync later. "
            "Peak day we processed about 4,200 check-ins with p95 under 300 milliseconds.",
            "What broke, and what did you do about it?",
            "The QR scanner double-submitted on flaky WiFi, creating duplicate rows. I added an idempotency "
            "key on the client and a unique constraint server-side, then backfilled 180 duplicates with a "
            "one-off script. After that, zero duplicates across the last two events.",
            "Walk me through how you'd design a rate limiter for our login API.",
            "First I'd ask what we're protecting against — credential stuffing, so per-account and per-IP "
            "limits, not just global. Token bucket in Redis, 5 attempts a minute per account with exponential "
            "backoff, fail-open if Redis is down because login availability beats perfect limiting, and I'd "
            "log fail-open events so we know our exposure window.",
            "Behavioural: tell me about a time you disagreed with a teammate.",
            "Situation: my co-lead wanted to rewrite the fest app in React Native two weeks before the event. "
            "Task: I had to keep us shippable. Action: I timeboxed a one-day spike, we measured the rewrite at "
            "three weeks minimum, and I proposed we ship the web app and revisit after. Result: we shipped on "
            "time, and we did do the rewrite — in the off season, properly.",
        ),
    ),
    (
        "mid_vague",
        {"Building", "Interview-Ready"},
        _t(
            "Tell me about a project you're proud of.",
            "I made an e-commerce website in my third year with React and Node. It had login, products, cart, "
            "everything basically. It went well and I learned a lot about full stack development.",
            "What was the hardest technical decision in it?",
            "Mostly deciding the database. I used MongoDB because it's flexible and popular for these apps. "
            "It worked fine for what we needed.",
            "How would you find why an API endpoint got slow?",
            "I would check the logs and see if there's an error. Maybe add caching, caching usually helps. "
            "If not I would ask a senior or search online for the issue.",
            "Tell me about a time you handled pressure.",
            "During exams we also had the project deadline so it was a lot of pressure. I managed my time and "
            "worked late and we submitted on time. The professor liked it.",
        ),
    ),
    (
        "weak_nonanswers",
        {"Not Ready", "Building"},
        _t(
            "Tell me about yourself and what you've been building.",
            "I am from Pune, I like coding and cricket. I know C and some Java from college.",
            "Pick any project and walk me through a decision you made in it.",
            "We had a group project but mostly my friend did the coding part, I did the report and the slides.",
            "Suppose a page loads slowly for users in one city only — how would you investigate?",
            "I don't know really. Maybe the internet is slow there? I haven't done this before.",
            "Tell me about a challenge you worked through recently.",
            "Nothing much comes to mind. College was mostly regular, nothing very challenging honestly.",
        ),
    ),
]


async def _one_run(cfg: dict, messages: list[dict]) -> tuple[str, int]:
    """One debrief generation -> (band, raw pct). ("PARSE-FAIL", -1) when the model's
    output couldn't be parsed — counted as instability, never a crash: a rubric that
    sometimes emits unparseable output is exactly the kind of drift this measures."""
    import httpx
    system = build_system_prompt(cfg, "")
    msgs = messages + [{"role": "user", "content": debrief_instruction(cfg)}]
    try:
        raw = await call_claude(
            system=system, messages=msgs,
            model=settings.MODEL_DEBRIEF, max_tokens=8000,
            # A full readout takes longer than the 60s default read window —
            # main.py's own debrief path runs a 240s clock for the same reason.
            timeout=httpx.Timeout(connect=5.0, read=240.0, write=10.0, pool=5.0),
        )
        m = re.search(r"\{.*\}", raw, re.DOTALL)  # same outermost-object salvage as main.py
        d = json.loads(m.group(0)) if m else None
    except Exception as e:
        print(f"    run error: {type(e).__name__}: {e}")
        d = None
    if not isinstance(d, dict):
        return "PARSE-FAIL", -1
    pct = int(d.get("overall", 0))
    return stages.band_for(pct), pct


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()

    if not settings.ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY is not set — cannot run.")
        return 2

    drift = False
    for label, zone, msgs in [(l, z, m) for (l, z, m) in GOLDENS]:
        cfg = dict(_BASE_CFG)
        results = []
        for i in range(args.runs):
            band, pct = await _one_run(cfg, msgs)
            results.append((band, pct))
            print(f"  {label} run {i + 1}/{args.runs}: {band} (raw {pct})")
        bands = [b for b, _ in results]
        pcts = [p for _, p in results]
        stable = len(set(bands)) == 1
        in_zone = set(bands) <= zone
        spread = (max(pcts) - min(pcts)) if pcts else 0
        sd = statistics.pstdev(pcts) if len(pcts) > 1 else 0.0
        verdict = "PASS" if (stable and in_zone) else ("DRIFT" if not stable else "OUT-OF-ZONE")
        if verdict != "PASS":
            drift = True
        print(f"{label}: {verdict} bands={sorted(set(bands))} zone={sorted(zone)} "
              f"raw spread={spread} sd={sd:.1f}\n")

    print("RESULT:", "DRIFT — the band is not yet an instrument; do not widen launch claims."
          if drift else "PASS — bands held still across runs.")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
