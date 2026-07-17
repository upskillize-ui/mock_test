#!/usr/bin/env python3
"""THE COST MATRIX — Capacity/Cost phase, item 3.

Runs 2 complete synthetic sessions per cell of {TEXT, AUDIO, VIDEO} x {10, 20, 45 min},
Realistic difficulty, Interview feedback (18 sessions), reads each session's stored cost
ledger, and prints the "Amit table": cost per student per session per mode in ₹ — then
projects 2,500 students x 1 session at 20 min and at 45 min, per mode.

THIS SPENDS REAL VENDOR MONEY. So, by the phase rules:
  * It PRINTS its projected vendor spend BEFORE starting anything.
  * It is a DRY RUN by default (prints the projection and the plan, spends nothing).
  * `--confirm` is required to actually run.
  * It ABORTS if the projection would exceed the budget caps — 500 Sarvam credits or
    $15 LLM total — unless `--over-caps` is ALSO passed (that flag IS the human go-ahead).
  * It tracks ACTUAL spend from the ledgers as it goes and hard-stops if a cap is crossed
    mid-run, so a bad estimate cannot run away.

    python scripts/cost_matrix.py                     # dry run: projection only, no spend
    python scripts/cost_matrix.py --confirm           # run, but abort if projection > caps
    python scripts/cost_matrix.py --confirm --over-caps   # run past the caps (explicit go-ahead)
"""
import argparse
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")  # ₹ and — on a cp1252 console
except Exception:
    pass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx  # noqa: E402
import synthetic_student as ss  # noqa: E402
from app.config import settings  # noqa: E402

MODES = ["TEXT", "AUDIO", "VIDEO"]
DURATIONS = [10, 20, 45]
SESSIONS_PER_CELL = 2
BUDGET_SARVAM_CREDITS = 500.0
BUDGET_LLM_USD = 15.0
STUDENTS = 2500

# ── Pre-run PROJECTION model (documented, conservative) ──────────────────────
# These are ESTIMATES used only to gate the spend before a single real call. The actual
# numbers come from the ledgers. Per Realistic/Fresher session the stage machine poses ~13
# answerable questions -> ~14 Haiku calls (greeting + turns) + 1 Sonnet debrief. Voice modes
# add interviewer-speech TTS seconds and answer STT seconds. Longer durations mean richer
# answers (more tokens, more spoken seconds) — the driver scales answer length with duration.
_EST = {
    # per session: (llm_usd, tts_seconds, stt_seconds) by mode+duration bucket
    "llm_usd": {10: 0.06, 20: 0.09, 45: 0.15},        # Haiku turns + one Sonnet debrief
    "tts_seconds": {10: 70, 20: 110, 45: 200},         # interviewer speech (voice modes only)
    "stt_seconds": {10: 90, 20: 150, 45: 260},         # student answers (voice modes only)
}


def _project() -> dict:
    tts_cps = settings.SARVAM_TTS_CREDITS_PER_SEC
    stt_cps = settings.SARVAM_STT_CREDITS_PER_SEC
    llm_usd = tts_credits = stt_credits = 0.0
    for mode in MODES:
        for d in DURATIONS:
            n = SESSIONS_PER_CELL
            llm_usd += _EST["llm_usd"][d] * n
            if mode in ("AUDIO", "VIDEO"):
                tts_credits += _EST["tts_seconds"][d] * tts_cps * n
                stt_credits += _EST["stt_seconds"][d] * stt_cps * n
    return {
        "llm_usd": round(llm_usd, 2),
        "sarvam_credits": round(tts_credits + stt_credits, 1),
        "tts_credits": round(tts_credits, 1),
        "stt_credits": round(stt_credits, 1),
    }


def _print_projection(proj: dict) -> bool:
    print("=" * 72)
    print("PROJECTED VENDOR SPEND for the full cost matrix (18 sessions)")
    print("=" * 72)
    print(f"  LLM (Anthropic)     : ~${proj['llm_usd']}   (cap ${BUDGET_LLM_USD})")
    print(f"  Sarvam credits      : ~{proj['sarvam_credits']}   (cap {BUDGET_SARVAM_CREDITS})")
    print(f"      of which TTS     : ~{proj['tts_credits']}")
    print(f"      of which STT     : ~{proj['stt_credits']}")
    print(f"  Rates used          : Sarvam TTS {settings.SARVAM_TTS_CREDITS_PER_SEC}/s, "
          f"STT {settings.SARVAM_STT_CREDITS_PER_SEC}/s, $1=₹{settings.USD_TO_INR}")
    print("  NB: Sarvam credit rates are the config placeholders — confirm them on the")
    print("      dashboard before trusting the credit projection.")
    over_llm = proj["llm_usd"] > BUDGET_LLM_USD
    over_sarvam = proj["sarvam_credits"] > BUDGET_SARVAM_CREDITS
    if over_llm or over_sarvam:
        print("\n  >>> PROJECTION EXCEEDS A BUDGET CAP:"
              + (" LLM" if over_llm else "") + (" Sarvam" if over_sarvam else ""))
        print("      Re-run with --over-caps to proceed anyway (explicit go-ahead), or lower")
        print("      SESSIONS_PER_CELL / drop the voice cells.")
    print("=" * 72)
    return not (over_llm or over_sarvam)


def run(base: str, over_caps: bool):
    token = ss.mint_token()
    # pre-warm the voice bank once so voice cells don't each pay to build it
    ss.prewarm_bank(45, "ritu")
    cells = {}                     # (mode, duration) -> list of ledger dicts
    spent_usd = spent_credits = 0.0
    with httpx.Client(timeout=300.0) as client:
        for mode in MODES:
            for d in DURATIONS:
                cells[(mode, d)] = []
                for _ in range(SESSIONS_PER_CELL):
                    res = ss.drive_session(client, base, token, mode=mode, duration_min=d,
                                           difficulty="Realistic", feedback="interview", verbose=True)
                    led = ss.read_ledger_from_db(res["session_id"]) if res["session_id"] else None
                    if led:
                        cells[(mode, d)].append(led)
                        spent_usd += led["llm"]["total_usd"]
                        spent_credits += led["tts"]["credits"] + led["stt"]["credits"]
                    print(f"    [{mode} {d}min] scored={res['scored']} "
                          f"running spend: ${spent_usd:.3f} LLM, {spent_credits:.1f} credits")
                    # ACTUAL-spend hard stop (belt and suspenders over the projection gate).
                    if not over_caps and (spent_usd > BUDGET_LLM_USD or spent_credits > BUDGET_SARVAM_CREDITS):
                        print("\n  >>> HARD STOP: actual spend crossed a cap mid-run. Halting the matrix.")
                        return cells, spent_usd, spent_credits
    return cells, spent_usd, spent_credits


def _avg_inr(ledgers: list[dict]) -> dict:
    if not ledgers:
        return {"total": None, "llm": None, "tts": None, "stt": None, "n": 0}
    n = len(ledgers)
    return {
        "total": round(sum(x["total_inr"] for x in ledgers) / n, 3),
        "llm": round(sum(x["llm"]["total_inr"] for x in ledgers) / n, 3),
        "tts": round(sum(x["tts"]["inr"] for x in ledgers) / n, 3),
        "stt": round(sum(x["stt"]["inr"] for x in ledgers) / n, 3),
        "n": n,
    }


def print_amit_table(cells: dict):
    print("\n" + "=" * 72)
    print("THE AMIT TABLE — cost per student per session (₹), Realistic / Interview")
    print("=" * 72)
    header = f"{'mode':<7}" + "".join(f"{str(d)+'min':>12}" for d in DURATIONS)
    print(header)
    for mode in MODES:
        row = f"{mode:<7}"
        for d in DURATIONS:
            a = _avg_inr(cells.get((mode, d), []))
            row += f"{('₹'+str(a['total'])) if a['total'] is not None else '—':>12}"
        print(row)
    print("\nPer-cell breakdown (avg ₹ over the cell's sessions):")
    for mode in MODES:
        for d in DURATIONS:
            a = _avg_inr(cells.get((mode, d), []))
            if a["total"] is not None:
                print(f"  {mode:<6} {d:>2}min  total ₹{a['total']:<7} "
                      f"(llm ₹{a['llm']}, tts ₹{a['tts']}, stt ₹{a['stt']}, n={a['n']})")

    print("\n" + "-" * 72)
    print(f"PROJECTION — {STUDENTS} students × 1 session each")
    print("-" * 72)
    for d in (20, 45):
        print(f"  at {d} min:")
        for mode in MODES:
            a = _avg_inr(cells.get((mode, d), []))
            if a["total"] is not None:
                print(f"    {mode:<6} ₹{a['total']}/student  ×{STUDENTS} = ₹{round(a['total']*STUDENTS):,}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the cost matrix (spends real vendor money).")
    ap.add_argument("--base", default=ss.DEFAULT_BASE)
    ap.add_argument("--confirm", action="store_true", help="actually run (default is a dry projection)")
    ap.add_argument("--over-caps", action="store_true", help="proceed even if the projection exceeds a budget cap (explicit go-ahead)")
    args = ap.parse_args()

    proj = _project()
    within = _print_projection(proj)
    print(f"Target backend : {args.base}")

    if not args.confirm:
        print("\nDRY RUN — no sessions run, nothing spent. Re-run with --confirm to execute.")
        return 0
    if not within and not args.over_caps:
        print("\nABORTED: projection exceeds a budget cap and --over-caps was not given.")
        return 3

    cells, usd, credits = run(args.base, args.over_caps)
    print_amit_table(cells)
    print(f"\nACTUAL TEST SPEND: ${usd:.3f} LLM, {credits:.1f} Sarvam credits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
