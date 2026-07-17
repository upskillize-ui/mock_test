"""Unit tests for the per-session cost ledger (Capacity/Cost phase, item 2).

Pure-logic tests against app/ledger.py — no DB, no network. The accumulator is in-process,
so each test uses its own session id and forgets it at the end.

Runnable with either:  python -m pytest tests/test_cost_ledger.py
                  or:  python tests/test_cost_ledger.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")
# Pin the rates so the math is deterministic regardless of the operator's env.
os.environ["USD_TO_INR"] = "80.0"
os.environ["SARVAM_CREDIT_TO_INR"] = "1.0"
os.environ["SARVAM_TTS_CREDITS_PER_SEC"] = "0.5"
os.environ["SARVAM_STT_CREDITS_PER_SEC"] = "0.5"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ledger  # noqa: E402
from app import stt as stt_mod  # noqa: E402
from app.config import settings  # noqa: E402

# Read the LIVE rate from config rather than assuming our env won took effect — under pytest,
# app.config may already have been imported by an earlier test before this module set its env,
# so the ledger uses whatever rate config actually holds. The token/credit MATH is what these
# tests lock; the ₹ conversion just multiplies by that live rate.
USD_INR = settings.USD_TO_INR


def test_empty_session_is_a_zeroed_ledger():
    led = ledger.build_ledger("empty-sid")
    assert led["llm"]["total_usd"] == 0.0
    assert led["tts"]["vendor_seconds"] == 0.0
    assert led["stt"]["seconds"] == 0.0
    assert led["total_inr"] == 0.0
    # A stored ledger explains its own numbers: the rates it used are always present.
    assert led["rates"]["usd_to_inr"] == USD_INR
    ledger.forget("empty-sid")


def test_haiku_llm_cost_math():
    # Haiku 4.5: $1/Mtok in, $5/Mtok out. Cache read 0.10x input, cache write 1.25x input.
    ledger.record_llm("sid-haiku", "claude-haiku-4-5-20251001", {
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_input_tokens": 2000,
        "cache_creation_input_tokens": 4000,
    })
    led = ledger.build_ledger("sid-haiku")
    # (1000*1 + 2000*1*0.1 + 4000*1*1.25 + 500*5) / 1e6 = 8700/1e6 = 0.0087
    expected_usd = 0.0087
    assert abs(led["llm"]["total_usd"] - expected_usd) < 1e-9
    assert abs(led["llm"]["total_inr"] - expected_usd * USD_INR) < 1e-4
    row = led["llm"]["by_model"]["claude-haiku-4-5-20251001"]
    assert row["calls"] == 1
    assert row["input_tokens"] == 1000
    ledger.forget("sid-haiku")


def test_dated_snapshot_resolves_to_family_price():
    # A dated id must price at its family rate (prefix match), not the default.
    ledger.record_llm("sid-sonnet", "claude-sonnet-4-6", {"input_tokens": 1_000_000, "output_tokens": 0})
    led = ledger.build_ledger("sid-sonnet")
    # Sonnet 4.6 input is $3/Mtok -> 1M tokens = $3.
    assert abs(led["llm"]["total_usd"] - 3.0) < 1e-9
    ledger.forget("sid-sonnet")


def test_multiple_calls_same_model_accumulate():
    ledger.record_llm("sid-acc", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 10})
    ledger.record_llm("sid-acc", "claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 10})
    led = ledger.build_ledger("sid-acc")
    row = led["llm"]["by_model"]["claude-haiku-4-5"]
    assert row["calls"] == 2
    assert row["input_tokens"] == 200
    assert row["output_tokens"] == 20
    ledger.forget("sid-acc")


def test_stt_seconds_flow_into_credits_and_inr():
    stt_mod.note_stt_seconds("sid-stt", 12.0)
    led = ledger.build_ledger("sid-stt")
    assert led["stt"]["seconds"] == 12.0
    assert led["stt"]["calls"] == 1
    # seconds -> credits -> ₹, at whatever rates config actually holds.
    exp_credits = 12.0 * settings.SARVAM_STT_CREDITS_PER_SEC
    assert abs(led["stt"]["credits"] - exp_credits) < 1e-4
    assert abs(led["stt"]["inr"] - exp_credits * settings.SARVAM_CREDIT_TO_INR) < 1e-4
    ledger.forget("sid-stt")


def test_record_llm_never_raises_on_junk():
    # Telemetry must never break a turn — garbage in is swallowed, not raised.
    ledger.record_llm("", "model", {"input_tokens": 1})   # no session id
    ledger.record_llm("sid-x", "", {"input_tokens": 1})     # no model
    ledger.record_llm("sid-x", "model", None)                # no usage
    led = ledger.build_ledger("sid-x")
    assert led["llm"]["total_usd"] == 0.0
    ledger.forget("sid-x")


def test_unpriced_model_uses_default_not_zero():
    ledger.record_llm("sid-unk", "some-future-model-9", {"input_tokens": 1_000_000, "output_tokens": 0})
    led = ledger.build_ledger("sid-unk")
    # Default input price is $3/Mtok -> must be > 0, never silently free.
    assert led["llm"]["total_usd"] > 0.0
    ledger.forget("sid-unk")


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
