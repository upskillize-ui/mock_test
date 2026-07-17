#!/usr/bin/env python3
"""CAPACITY RAMP — Capacity/Cost phase, item 4.

Against the DEPLOYED Space, ramp concurrent synthetic TEXT sessions (the cheapest path):
5 -> 10 -> 20 -> 40, measuring per-turn latency and error rate at each step, and STOP at the
knee (median per-turn latency doubling vs the first step, or errors appearing). Then a small
mixed run (3 AUDIO + a spread of TEXT) to measure the voice path's extra weight.

Delivers: the max safe concurrent sessions on the current hardware, and the observed
bottleneck named with evidence (latency curve + error onset).

THIS SPENDS REAL VENDOR MONEY and LOADS THE DEPLOYED SPACE. So:
  * DRY RUN by default — prints the projection and the plan, spends nothing.
  * `--confirm` required to actually run.
  * Prints projected spend BEFORE starting.
  * Run with MAX_CONCURRENT_SESSIONS UNSET (0) on the Space, or the safety valve masks the
    natural knee (you'd measure the cap, not the hardware). The script warns about this.

    python scripts/capacity_ramp.py --base https://<space> --confirm
"""
import argparse
import statistics
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")  # ₹ and — on a cp1252 console
except Exception:
    pass
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx  # noqa: E402
import synthetic_student as ss  # noqa: E402

STEPS = [5, 10, 20, 40]
EST_LLM_USD_PER_TEXT = 0.09     # ~14 Haiku turns + one Sonnet debrief, 20-min TEXT session
KNEE_LATENCY_MULT = 2.0         # median per-turn latency this many x the baseline == knee


def _run_wave(base: str, token: str, n: int, mode: str = "TEXT", duration: int = 20) -> dict:
    """Fire n sessions concurrently; collect per-turn latencies and errors."""
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = []
        for _ in range(n):
            # one client per session (per thread) — mirrors n independent browsers
            def _one():
                with httpx.Client(timeout=300.0) as c:
                    return ss.drive_session(c, base, token, mode=mode, duration_min=duration,
                                            difficulty="Realistic", feedback="interview")
            futs.append(ex.submit(_one))
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                results.append({"ok": False, "errors": [f"thread {type(e).__name__}: {e}"],
                                "per_turn_latency_ms": [], "session_id": None})
    wall = time.time() - t0
    lat = [ms for r in results for ms in r.get("per_turn_latency_ms", [])]
    n_err_sessions = sum(1 for r in results if r.get("errors"))
    n_holds = sum(1 for r in results if "capacity_hold" in (r.get("errors") or []))
    return {
        "concurrency": n,
        "sessions_ok": sum(1 for r in results if r.get("ok")),
        "sessions_err": n_err_sessions,
        "capacity_holds": n_holds,
        "turn_count": len(lat),
        "median_ms": int(statistics.median(lat)) if lat else None,
        "p95_ms": int(sorted(lat)[int(len(lat) * 0.95)]) if lat else None,
        "wall_s": round(wall, 1),
        "errors_sample": [e for r in results for e in (r.get("errors") or [])][:5],
    }


def _project():
    total_text = sum(STEPS)                 # worst case: every step runs fully
    mixed_text, mixed_audio = 7, 3
    usd = (total_text + mixed_text) * EST_LLM_USD_PER_TEXT + mixed_audio * 0.12
    return round(usd, 2), total_text + mixed_text, mixed_audio


def main() -> int:
    ap = argparse.ArgumentParser(description="Ramp concurrency against the deployed Space (spends money).")
    ap.add_argument("--base", default=ss.DEFAULT_BASE)
    ap.add_argument("--confirm", action="store_true", help="actually run (default is a dry projection)")
    args = ap.parse_args()

    usd, n_text, n_audio = _project()
    print("=" * 72)
    print("CAPACITY RAMP — projected spend & plan")
    print("=" * 72)
    print(f"  Steps               : {STEPS} concurrent TEXT sessions, stop at the knee")
    print(f"  Then                : 1 mixed wave (3 AUDIO + 7 TEXT)")
    print(f"  Worst-case sessions : ~{n_text} TEXT + {n_audio} AUDIO (fewer if the knee is early)")
    print(f"  Projected LLM spend : ~${usd}  (TEXT is cheap; no Sarvam on TEXT)")
    print(f"  Target Space        : {args.base}")
    print("  WARNING: run with MAX_CONCURRENT_SESSIONS unset (0) on the Space, or the safety")
    print("           valve will hold sessions and you will measure the CAP, not the knee.")
    print("=" * 72)

    if not args.confirm:
        print("\nDRY RUN — nothing run, nothing spent. Re-run with --confirm to execute.")
        return 0

    token = ss.mint_token()
    baseline = None
    knee = None
    rows = []
    for n in STEPS:
        print(f"\n-- wave: {n} concurrent TEXT sessions --")
        row = _run_wave(args.base, token, n)
        rows.append(row)
        print(f"   ok={row['sessions_ok']}/{n}  errs={row['sessions_err']}  holds={row['capacity_holds']}  "
              f"median/turn={row['median_ms']}ms  p95={row['p95_ms']}ms  wall={row['wall_s']}s")
        if row["errors_sample"]:
            print(f"   errors: {row['errors_sample']}")
        if baseline is None and row["median_ms"]:
            baseline = row["median_ms"]
        # Knee test: errors appeared, or median latency doubled vs baseline.
        latency_knee = baseline and row["median_ms"] and row["median_ms"] >= KNEE_LATENCY_MULT * baseline
        if row["sessions_err"] > 0 or latency_knee:
            knee = n
            reason = "errors" if row["sessions_err"] > 0 else f"latency ≥{KNEE_LATENCY_MULT}× baseline"
            print(f"   >>> KNEE at {n} concurrent ({reason}). Stopping ramp.")
            break

    print(f"\n-- mixed wave: 3 AUDIO + 7 TEXT --")
    ss.prewarm_bank(20, "ritu")
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = []
        for i in range(10):
            mode = "AUDIO" if i < 3 else "TEXT"
            def _one(m=mode):
                with httpx.Client(timeout=300.0) as c:
                    return ss.drive_session(c, args.base, token, mode=m, duration_min=20,
                                            difficulty="Realistic", feedback="interview")
            futs.append(ex.submit(_one))
        mixed = [f.result() for f in as_completed(futs)]
    mlat = [ms for r in mixed for ms in r.get("per_turn_latency_ms", [])]
    print(f"   mixed ok={sum(1 for r in mixed if r.get('ok'))}/10  "
          f"median/turn={int(statistics.median(mlat)) if mlat else None}ms")

    print("\n" + "=" * 72)
    print("RESULT")
    print("=" * 72)
    max_safe = max((r["concurrency"] for r in rows if r["sessions_err"] == 0 and
                    (baseline is None or (r["median_ms"] or 0) < KNEE_LATENCY_MULT * baseline)),
                   default=0)
    print(f"  Baseline median/turn : {baseline}ms")
    print(f"  Knee at              : {knee if knee else '> ' + str(STEPS[-1]) + ' (no knee reached)'} concurrent")
    print(f"  Max SAFE concurrent  : {max_safe} TEXT sessions on current hardware")
    print("  Bottleneck: read the latency curve above against the DB pool ceiling (15) and")
    print("  CPU. If the knee is at/near 15, the DB pool (a request pins its connection across")
    print("  the LLM await) is the wall — see scripts/db_pool_audit.py and the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
