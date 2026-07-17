"""Item 8 — attention call-outs are rare, late, gentle, never in warm-up, at most once.

The interviewer used to say "your attention drifted… in a real panel that costs you" on the
first tab-switch and again every turn after. These guardrails pin the new behaviour:
never in WARMUP, only after several signals, at most once per session, gentle register only.

Runnable with:  python -m pytest tests/test_attention_callouts.py
           or:  python tests/test_attention_callouts.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import presence as pr  # noqa: E402
from app import main as m  # noqa: E402


class _Mappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _Mappings(self._rows)


class FakeDB:
    """Returns the given {event_type: count} as focus-event rows for _focus_counts."""
    def __init__(self, counts):
        self.rows = [{"event_type": k, "n": v} for k, v in counts.items()]

    def execute(self, *a, **k):
        return _Result(self.rows)


def _note(counts, stage, camera_at_join=False):
    m._ATTENTION_NOTED.discard("sid")   # isolate each call
    return m._presence_note(FakeDB(counts), {"id": "sid", "camera_at_join": camera_at_join}, stage)


# ── The gentle copy ──────────────────────────────────────────────────────────

def test_gentle_note_is_gentle_and_non_empty():
    note = pr.attention_note_gentle().lower()
    assert note.strip()
    for banned in ("cost you", "costs you", "cheat", "reprimand", "accus", "penal", "threat"):
        assert banned not in note, f"gentle attention note must not contain {banned!r}"


def test_the_costs_you_copy_is_gone_from_the_live_path():
    # escalation_directive still exists (ladder meaning / avatar register / older tests), but
    # the SPOKEN in-session note now comes from attention_note_gentle, which never says it.
    assert "cost" not in pr.attention_note_gentle().lower()


# ── Never during warm-up ─────────────────────────────────────────────────────

def test_no_attention_note_in_warmup_even_with_many_events():
    assert _note({"tab_hidden": 9}, "WARMUP") == ""


# ── Rare: below the threshold, nothing ───────────────────────────────────────

def test_below_min_events_is_silent():
    below = m.settings.ATTENTION_MIN_EVENTS - 1
    assert _note({"tab_hidden": below}, "DOMAIN") == ""


# ── Fires once, late, gently ─────────────────────────────────────────────────

def test_fires_gently_past_warmup_at_threshold():
    note = _note({"tab_hidden": m.settings.ATTENTION_MIN_EVENTS}, "DOMAIN")
    assert note == pr.attention_note_gentle()
    assert "cost" not in note.lower()


def test_at_most_once_per_session():
    counts = {"tab_hidden": m.settings.ATTENTION_MIN_EVENTS + 3}
    db = FakeDB(counts)
    row = {"id": "sid-once", "camera_at_join": False}
    m._ATTENTION_NOTED.discard("sid-once")
    first = m._presence_note(db, row, "DOMAIN")
    second = m._presence_note(db, row, "BEHAVIOURAL")   # a later turn, still drifting
    assert first == pr.attention_note_gentle()
    assert second == "", "the attention note must fire at most once per session"
    m._ATTENTION_NOTED.discard("sid-once")


# ── The camera DEVICE ladder is unchanged (separate concern) ─────────────────

def test_camera_off_still_nudges_regardless_of_stage():
    # A camera-on joiner whose camera goes off still gets the device nudge, even in WARMUP —
    # that ladder is about turning the camera back on, not the attention nag.
    note = _note({"camera_off": 1}, "WARMUP", camera_at_join=True)
    assert note == pr.camera_directive("nudge")


# ── The kill switch ──────────────────────────────────────────────────────────

def test_disabled_flag_silences_attention_notes():
    orig = m.settings.ATTENTION_CALLOUTS_ENABLED
    m.settings.ATTENTION_CALLOUTS_ENABLED = False
    try:
        assert _note({"tab_hidden": 20}, "DOMAIN") == ""
    finally:
        m.settings.ATTENTION_CALLOUTS_ENABLED = orig


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
