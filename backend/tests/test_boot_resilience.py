"""Item 5 — startup must survive a dead TTS account.

The Space must never sit in "Restarting" because the Sarvam account ran dry, and a session
must stay playable (silently, with captions) when TTS is unavailable. These tests pin that
contract WITHOUT a real vendor, a real DB, or a running server — the vendor call is
monkeypatched, exactly like test_tts.py.

  - Boot warming is HARD-bounded: a hung vendor can't block boot or leave a zombie task.
  - Warming is skipped (with a log) when TTS is on but there is no key.
  - Warming is best-effort: total vendor failure warms nothing and never raises.
  - Mid-session, a failing TTS yields caption-only playback (null audio), never a crash.

Runnable with:  python -m pytest tests/test_boot_resilience.py
           or:  python tests/test_boot_resilience.py
"""
import asyncio
import os
import sys
import tempfile
import time

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")
# A dedicated, empty cache dir so warming never sees a pre-warmed clip and every test
# exercises the vendor path deterministically.
os.environ["TTS_CACHE_DIR"] = os.path.join(tempfile.gettempdir(), "iq_boot_test_cache")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import tts as t  # noqa: E402

# Force the empty test cache dir onto the ALREADY-IMPORTED settings object. Setting the env var
# above only works if nothing has imported app.config yet — which used to hold only because this
# file sorted first alphabetically. A test that sorts earlier (e.g. test_api_key_hardening.py)
# imports config first, binding the REAL tts_cache dir, and then warming would see pre-warmed
# clips and these best-effort assertions would break. Pinning it here makes the dir
# order-independent, which is what it always meant to be.
t.settings.TTS_CACHE_DIR = os.environ["TTS_CACHE_DIR"]


# ── helpers ─────────────────────────────────────────────────────────────────

class _tts_env:
    """Set TTS_ENABLED / SARVAM_API_KEY for the body and always restore them."""
    def __init__(self, enabled=True, key="invalid-key"):
        self.enabled, self.key = enabled, key

    def __enter__(self):
        self._e, self._k = t.settings.TTS_ENABLED, t.settings.SARVAM_API_KEY
        t.settings.TTS_ENABLED, t.settings.SARVAM_API_KEY = self.enabled, self.key
        return self

    def __exit__(self, *a):
        t.settings.TTS_ENABLED, t.settings.SARVAM_API_KEY = self._e, self._k


def _patch_synth(fn):
    orig = t.synthesize
    t.synthesize = fn
    return orig


# ── 1) TTS disabled: warming is a clean no-op, no vendor call ────────────────

def test_warming_is_a_noop_when_tts_disabled():
    async def _boom(text, speaker, *, timeout=None):
        raise AssertionError("synthesize must not be called when TTS is disabled")
    orig = _patch_synth(_boom)
    try:
        with _tts_env(enabled=False, key="whatever"):
            summary = asyncio.run(t.warm_clip_pack([t.resolve_voice("female")]))
        assert summary["warmed"] == 0 and summary["failed"] == 0
    finally:
        t.synthesize = orig


# ── 2) Total vendor failure (e.g. an invalid key -> 401 -> None): best-effort ─

def test_warming_is_best_effort_when_every_synth_fails():
    async def _fail(text, speaker, *, timeout=None):
        return None
    orig = _patch_synth(_fail)
    try:
        with _tts_env(enabled=True, key="invalid-key"):
            summary = asyncio.run(t.warm_clip_pack([t.resolve_voice("female")]))
        assert summary["warmed"] == 0
        assert summary["failed"] == len(t.clip_pack_lines())   # every line tried, all failed
        assert summary["cached"] == 0
    finally:
        t.synthesize = orig


# ── 3) A HUNG vendor cannot block boot: the hard timeout/budget bounds it ─────

def test_a_hanging_vendor_is_bounded_and_never_blocks_boot():
    async def _hang(text, speaker, *, timeout=None):
        await asyncio.sleep(60)   # simulate a black-hole TCP that never answers
    orig = _patch_synth(_hang)
    try:
        with _tts_env(enabled=True, key="invalid-key"):
            start = time.monotonic()
            summary = asyncio.run(t.warm_clip_pack(
                [t.resolve_voice("female")],
                per_call_timeout=0.05, budget_seconds=0.2,
            ))
            elapsed = time.monotonic() - start
        # It must return in well under the 60s hang — the per-call ceiling + overall budget
        # are what stop a dead account holding the boot open.
        assert elapsed < 5.0, f"warming took {elapsed:.1f}s — it was not bounded"
        # Nothing warmed; the clips it couldn't reach are failed or left for first-use.
        assert summary["warmed"] == 0
        assert summary["failed"] + summary["skipped"] == len(t.clip_pack_lines())
    finally:
        t.synthesize = orig


# ── 4) The boot hook skips warming (with a log) when it can't warm ───────────

def test_boot_hook_skips_warming_when_it_cannot_warm():
    from app import main as m
    called = {"n": 0}
    async def _should_not_run(*a, **k):
        called["n"] += 1
        return {"warmed": 0, "cached": 0, "failed": 0, "skipped": 0, "bytes": 0}
    orig = t.warm_clip_pack
    t.warm_clip_pack = _should_not_run
    try:
        # TTS off -> return immediately, no warm, no background task.
        with _tts_env(enabled=False, key=""):
            assert asyncio.run(m.warm_clip_pack_on_boot()) is None
        # TTS on but no SARVAM key -> log + return, still no warm. This is the item's
        # "if TTS is unavailable at boot, log it, skip warming, and start anyway".
        with _tts_env(enabled=True, key=""):
            assert asyncio.run(m.warm_clip_pack_on_boot()) is None
        assert called["n"] == 0, "the hook must not warm when there is nothing to warm with"
    finally:
        t.warm_clip_pack = orig


# ── 5) Mid-session: a failing TTS yields caption-only playback, never a crash ─

def test_mid_session_tts_failure_is_caption_only_never_a_crash():
    from app import main as m
    async def _fail(text, speaker, *, timeout=None):
        return None
    orig = _patch_synth(_fail)
    try:
        with _tts_env(enabled=True, key="invalid-key"):
            # A reply splits into sentences; each carries a caption but a NULL audio_url.
            segs = asyncio.run(m._try_tts_segments(
                "sess-silent", "First point. Second point. And the question?", "female"))
            assert [s["text"] for s in segs] == ["First point.", "Second point.", "And the question?"]
            assert all(s["audio_url"] is None for s in segs)   # captions, no audio
            assert not any(s["pending"] for s in segs)         # not "still synthesising" — just silent

            # The single-line path (re-ask / rating ask) is None, never an exception.
            assert asyncio.run(m._try_tts("sess-silent", "One more thing.", "female")) is None
    finally:
        t.synthesize = orig


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
