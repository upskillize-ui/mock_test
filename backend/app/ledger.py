"""Per-session COST LEDGER — permanent product telemetry (Capacity/Cost phase, item 2).

Every session, real student or synthetic driver, accrues a ledger:

  * LLM spend, per model, split into input / output / cache-read / cache-write tokens → $
  * Sarvam TTS: audio SECONDS we actually paid the vendor for → credits
  * Sarvam STT: audio SECONDS the learner spoke → credits
  * a single ₹ total, at the stated $/₹ and credit/₹ rates

WHY IN-PROCESS, LIKE THE TTS/STT METERS IT SITS BESIDE
  tts.session_cost() and stt already keep per-session, in-process, no-DB meters (a restart
  mid-session under-counts that one session, which is acceptable for a measurement and is
  never used to bill a student). This ledger is the same shape and the same honesty: it is
  ACCOUNTING, not an invoice. It reads the TTS seconds tts.py already measures and the STT
  seconds stt.py now measures, and it accumulates LLM usage that claude_client hands it on
  every call. At /session/end it is assembled once and written onto the session row
  (main._finalize_session); nothing here ever raises into a live interview.

RATES ARE CONFIG, NOT CONSTANTS
  The $/₹ rate, the credit/₹ rate, and the Sarvam per-second credit rates are the inputs the
  report is required to STATE, and they change with the vendor plan and the forex rate — so
  they live in app.config (env-overridable), and build_ledger() echoes the exact rates it
  used back into the ledger so a stored ledger is self-describing after the fact.
"""

import logging
import threading

from .config import settings

log = logging.getLogger(__name__)


# ── LLM price book (USD per 1,000,000 tokens) ────────────────────────────────
# Matched by PREFIX so a dated snapshot (claude-haiku-4-5-20251001) resolves to its family
# rate. Cache reads bill at ~0.10x input and cache writes at ~1.25x input (Anthropic prompt
# caching) — the interview system prompt is cached, so those two token classes are the bulk
# of the input side and are priced separately rather than at full input rate.
_USD_PER_MTOK = {
    "claude-haiku-4-5":  {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00},
    "claude-sonnet-5":   {"in": 3.00, "out": 15.00},
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00},
    "claude-opus-4-7":   {"in": 5.00, "out": 25.00},
}
# Charged as a fraction of the model's INPUT rate.
_CACHE_READ_MULT = 0.10
_CACHE_WRITE_MULT = 1.25
# Any model not in the book falls back to this so a model swap never divides-by-zero or
# silently prices at 0. Logged once so an unpriced model is visible, not invisible.
_DEFAULT_PRICE = {"in": 3.00, "out": 15.00}
_unpriced_seen: set[str] = set()


def _price_for(model: str) -> dict:
    for prefix, price in _USD_PER_MTOK.items():
        if model and model.startswith(prefix):
            return price
    if model not in _unpriced_seen:
        _unpriced_seen.add(model)
        log.warning("cost ledger: no price for model %r — using default %s/Mtok", model, _DEFAULT_PRICE)
    return _DEFAULT_PRICE


# ── Per-session LLM accumulator ──────────────────────────────────────────────
# session_id -> {model -> {calls, input_tokens, output_tokens, cache_read, cache_creation}}.
# Guarded by a lock: turn calls are async and the streaming path records from inside the
# event loop, so two coroutines for the same session could touch the same row.
_lock = threading.Lock()
_llm: dict[str, dict[str, dict]] = {}


def _empty_model_row() -> dict:
    return {
        "calls": 0,
        "input_tokens": 0,        # uncached input only (full input rate)
        "output_tokens": 0,
        "cache_read_tokens": 0,   # served from cache (~0.10x input)
        "cache_creation_tokens": 0,  # written to cache (~1.25x input)
    }


def record_llm(session_id: str, model: str, usage: dict | None) -> None:
    """Record one Anthropic call's token usage against this session.

    `usage` is the Anthropic response `usage` object (or the streamed equivalent):
    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens.
    Never raises — a telemetry write must never be able to break a turn or a debrief.
    """
    if not session_id or not model or not isinstance(usage, dict):
        return
    try:
        with _lock:
            per_model = _llm.setdefault(session_id, {})
            row = per_model.setdefault(model, _empty_model_row())
            row["calls"] += 1
            row["input_tokens"] += int(usage.get("input_tokens") or 0)
            row["output_tokens"] += int(usage.get("output_tokens") or 0)
            row["cache_read_tokens"] += int(usage.get("cache_read_input_tokens") or 0)
            row["cache_creation_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
    except Exception as e:  # defensive: telemetry never breaks the interview
        log.warning("cost ledger record_llm failed: %s", type(e).__name__)


def _llm_cost_usd(row: dict, price: dict) -> float:
    return (
        row["input_tokens"] * price["in"]
        + row["cache_read_tokens"] * price["in"] * _CACHE_READ_MULT
        + row["cache_creation_tokens"] * price["in"] * _CACHE_WRITE_MULT
        + row["output_tokens"] * price["out"]
    ) / 1_000_000.0


def build_ledger(session_id: str) -> dict:
    """Assemble the full per-session cost ledger. Pure read — safe to call more than once
    (idempotent), which /session/end relies on. Pulls TTS seconds from tts.session_cost()
    and STT seconds from stt.session_seconds(); both return a zeroed shape when nothing
    happened, so the keys are always present.

    Returns a JSON-serialisable dict with an `llm`, `tts`, `stt` block, a `total_inr`, and
    the `rates` actually used, so a stored ledger explains its own numbers.
    """
    # Imported here (not at module top) purely to keep the import graph a DAG: tts/stt do
    # not import ledger, and this defers their import to call time.
    from . import tts, stt

    usd_inr = settings.USD_TO_INR
    credit_inr = settings.SARVAM_CREDIT_TO_INR

    # ── LLM ──────────────────────────────────────────────────────────────────
    with _lock:
        per_model = {m: dict(r) for m, r in _llm.get(session_id, {}).items()}
    by_model = {}
    llm_usd = 0.0
    for model, row in per_model.items():
        price = _price_for(model)
        cost = _llm_cost_usd(row, price)
        llm_usd += cost
        by_model[model] = {
            **row,
            "usd": round(cost, 6),
        }
    llm = {
        "by_model": by_model,
        "total_usd": round(llm_usd, 6),
        "total_inr": round(llm_usd * usd_inr, 4),
    }

    # ── TTS (seconds already measured by tts.py) ─────────────────────────────
    tts_meter = tts.session_cost(session_id)
    tts_seconds = float(tts_meter.get("vendor_seconds") or 0.0)  # billed seconds only
    tts_credits = tts_seconds * settings.SARVAM_TTS_CREDITS_PER_SEC
    tts_block = {
        "vendor_seconds": round(tts_seconds, 1),
        "cached_seconds": tts_meter.get("cached_seconds", 0.0),
        "cache_saved_pct": tts_meter.get("cache_saved_pct", 0),
        "credits": round(tts_credits, 4),
        "inr": round(tts_credits * credit_inr, 4),
    }

    # ── STT (seconds now measured by stt.py) ─────────────────────────────────
    stt_meter = stt.session_seconds(session_id)
    stt_seconds = float(stt_meter.get("seconds") or 0.0)
    stt_credits = stt_seconds * settings.SARVAM_STT_CREDITS_PER_SEC
    stt_block = {
        "seconds": round(stt_seconds, 1),
        "calls": stt_meter.get("calls", 0),
        "seconds_estimated": stt_meter.get("estimated", False),
        "credits": round(stt_credits, 4),
        "inr": round(stt_credits * credit_inr, 4),
    }

    total_inr = round(llm["total_inr"] + tts_block["inr"] + stt_block["inr"], 4)

    return {
        "llm": llm,
        "tts": tts_block,
        "stt": stt_block,
        "total_inr": total_inr,
        "rates": {
            "usd_to_inr": usd_inr,
            "sarvam_credit_to_inr": credit_inr,
            "sarvam_tts_credits_per_sec": settings.SARVAM_TTS_CREDITS_PER_SEC,
            "sarvam_stt_credits_per_sec": settings.SARVAM_STT_CREDITS_PER_SEC,
        },
    }


def forget(session_id: str) -> None:
    """Drop a session's in-process LLM accumulator once its ledger is persisted, so a
    long-lived process does not grow one row per session forever. Best-effort."""
    with _lock:
        _llm.pop(session_id, None)
