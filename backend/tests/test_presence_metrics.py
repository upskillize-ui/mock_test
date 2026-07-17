"""Phase D — presence metrics m1–m8.

Guards the promises that must never regress:
  * PRIVACY / TRUST — the wire is eight numbers; sanitisation drops everything else.
  * REPORT-ONLY    — m1–m8 never carry a band, a score, or a benchmark. A camera-on
                     session and the same session camera-off land on the SAME readiness.
  * VIDEO ONLY     — AUDIO/TEXT, a camera-off join, or a MediaPipe failure all degrade to
                     the no-data line, and it is NEVER a penalty.
  * HONESTY        — every behaviour sentence is free of emotion attribution.
  * DARK           — with the flag off, /session/presence does not exist (404) and no
                     metric is ever computed, stored, or shown.

Runnable with:  python -m pytest tests/test_presence_metrics.py
"""
import os
import re
import sys
import json

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import presence as pr  # noqa: E402
from app.main import app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.auth import current_user  # noqa: E402
import app.main as main  # noqa: E402


# ── Sanitisation: the whole trust boundary ───────────────────────────────────

def test_sanitize_keeps_only_the_eight_known_numbers():
    raw = {"m1": 0.9, "m3": 4, "m9": 1.0, "landmarks": [[1, 2, 3]], "note": "nervous"}
    out = pr.sanitize_presence_metrics(raw)
    assert out == {"m1": 0.9, "m3": 4}
    assert "m9" not in out and "landmarks" not in out and "note" not in out


def test_sanitize_clamps_ratios_and_floors_counts():
    out = pr.sanitize_presence_metrics({"m1": 1.7, "m2": -0.3, "m3": -5, "m5": 0.5})
    assert out["m1"] == 1.0 and out["m2"] == 0.0
    assert out["m3"] == 0 and out["m5"] == 0.5


def test_sanitize_drops_nan_inf_and_junk():
    out = pr.sanitize_presence_metrics(
        {"m1": float("nan"), "m2": float("inf"), "m4": "not a number", "m5": 0.7})
    assert "m1" not in out and "m2" not in out and "m4" not in out
    assert out == {"m5": 0.7}


def test_sanitize_returns_none_when_nothing_survives():
    assert pr.sanitize_presence_metrics({}) is None
    assert pr.sanitize_presence_metrics({"x": 1}) is None
    assert pr.sanitize_presence_metrics("not a dict") is None
    assert pr.sanitize_presence_metrics(None) is None


def test_count_is_capped():
    out = pr.sanitize_presence_metrics({"m3": 10_000})
    assert out["m3"] == pr.PRESENCE_COUNT_CAP


# ── VIDEO only, and every other path is a no-op (not a penalty) ───────────────

FULL = {"m1": 0.8, "m2": 0.7, "m3": 3, "m4": 0.5, "m5": 0.4, "m6": 0.9, "m7": 0.6, "m8": 0.85}


def test_available_only_for_video_with_camera_and_metrics():
    assert pr.presence_metrics_available("VIDEO", True, FULL) is True
    assert pr.presence_metrics_available("AUDIO", True, FULL) is False
    assert pr.presence_metrics_available("TEXT", True, FULL) is False
    assert pr.presence_metrics_available("VIDEO", False, FULL) is False   # camera-off join
    assert pr.presence_metrics_available("VIDEO", True, {}) is False       # nothing measured
    assert pr.presence_metrics_available("video", True, FULL) is True      # case-insensitive


def test_readout_measured_only_for_video_with_data():
    out = pr.presence_metrics_readout(FULL, "VIDEO", True)
    assert out["measured"] is True
    assert out["report_only"] is True
    assert len(out["metrics"]) == 8
    # Every row is behaviour: an id, a label, a display value, a sentence.
    for row in out["metrics"]:
        assert row["id"] in pr.PRESENCE_METRIC_KEYS
        assert row["label"] and row["display"] and row["behaviour"]


def test_readout_is_the_no_data_line_for_every_other_path():
    for mode, cam in [("AUDIO", True), ("TEXT", True), ("VIDEO", False)]:
        out = pr.presence_metrics_readout(FULL, mode, cam)
        assert out["measured"] is False
        assert out["note"] == pr.PRESENCE_METRICS_NO_DATA
    # MediaPipe-failure looks identical: VIDEO + camera on, but no numbers arrived.
    out = pr.presence_metrics_readout(None, "VIDEO", True)
    assert out["measured"] is False and out["note"] == pr.PRESENCE_METRICS_NO_DATA


# ── REPORT-ONLY: no band, no score, anywhere in the block ────────────────────

def test_readout_carries_no_band_or_score_key():
    out = pr.presence_metrics_readout(FULL, "VIDEO", True)
    flat = json.dumps(out).lower()
    for forbidden in ("band", "benchmark", "score", "/10", "ready", "pass", "fail"):
        assert forbidden not in flat, f"presence block leaked a scoring word: {forbidden}"


def test_only_omitted_metrics_are_absent_the_rest_render():
    partial = {"m1": 0.9, "m5": 0.2}   # a MediaPipe run that measured only two
    out = pr.presence_metrics_readout(partial, "VIDEO", True)
    ids = {r["id"] for r in out["metrics"]}
    assert ids == {"m1", "m5"}


# ── HONESTY: no emotion attribution in any string this module can emit ───────

BANNED = (
    "nervous", "anxious", "bored", "confident", "unconfident", "shy", "arrogant",
    "insecure", "calm", "relaxed", "comfortable", "uncomfortable", "composed",
    "composure", "engaged", "disengaged", "happy", "sad", "angry", "afraid",
    "emotion", "feel", "feeling", "mood", "seemed", "cheat",
)


def _every_string_the_module_emits():
    out = [pr.PRESENCE_METRICS_NO_DATA]
    out += [m["label"] for m in pr.PRESENCE_METRICS]
    # Ratio sentences across all three bands.
    for v in (0.9, 0.5, 0.1):
        for spec in pr.PRESENCE_METRICS:
            if spec["kind"] == "ratio":
                out.append(pr._sentence_for(spec["id"], v))
    # Count sentences across a range.
    for n in range(0, 12):
        out.append(pr._sentence_for("m3", n))
    return [s for s in out if s]


def test_no_emotion_word_in_any_presence_metric_copy():
    for s in _every_string_the_module_emits():
        low = s.lower()
        for w in BANNED:
            assert not re.search(rf"\b{re.escape(w)}\b", low), f"emotion word {w!r} in: {s}"


def test_every_metric_has_a_behaviour_sentence_at_every_band():
    for spec in pr.PRESENCE_METRICS:
        if spec["kind"] == "ratio":
            for v in (0.9, 0.5, 0.1):
                assert pr._sentence_for(spec["id"], v), f"{spec['id']} @ {v} empty"
        else:
            for n in (0, 8):
                assert pr._sentence_for(spec["id"], n)


# ── Endpoint: DARK by default, VIDEO-only when lit, report-only always ────────

class _Result:
    def __init__(self, row):
        self._row = row
    def mappings(self):
        return self
    def first(self):
        return self._row


class RecordingDB:
    """Returns the session row for a SELECT; records UPDATEs so we can assert on them."""
    def __init__(self, session_row):
        self.session_row = session_row
        self.updates = []
    def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.strip().upper().startswith("UPDATE") or "UPDATE vyom_sessions" in sql:
            self.updates.append((sql, params))
            return _Result(None)
        if "vyom_sessions" in sql:
            return _Result(self.session_row)
        return _Result(None)
    def commit(self):
        pass


def _session_row(session_mode="VIDEO", camera=True):
    return {"id": "sid-1", "user_id": "u1", "status": "active", "deleted_at": None,
            "session_mode": session_mode, "camera_at_join": 1 if camera else 0}


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_user] = lambda: "u1"
    return TestClient(app)


def _cleanup():
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(current_user, None)


def test_endpoint_is_404_while_dark():
    old = main.settings.PRESENCE_METRICS_ENABLED
    main.settings.PRESENCE_METRICS_ENABLED = False
    db = RecordingDB(_session_row())
    try:
        r = _client(db).post("/session/presence", json={"session_id": "sid-1", "m1": 0.8})
        assert r.status_code == 404
        assert db.updates == []   # nothing computed, nothing stored
    finally:
        main.settings.PRESENCE_METRICS_ENABLED = old
        _cleanup()


def test_endpoint_stores_for_a_video_session_when_enabled():
    old = main.settings.PRESENCE_METRICS_ENABLED
    main.settings.PRESENCE_METRICS_ENABLED = True
    db = RecordingDB(_session_row(session_mode="VIDEO", camera=True))
    try:
        r = _client(db).post("/session/presence",
                             json={"session_id": "sid-1", "m1": 1.5, "m3": 4, "bogus": 9})
        assert r.status_code == 200
        body = r.json()
        assert body["stored"] is True and body["report_only"] is True
        assert len(db.updates) == 1
        # The stored JSON is the SERVER-clamped set, not the raw client payload.
        stored = json.loads(db.updates[0][1]["m"])
        assert stored == {"m1": 1.0, "m3": 4}
    finally:
        main.settings.PRESENCE_METRICS_ENABLED = old
        _cleanup()


def test_endpoint_stores_nothing_for_audio_or_camera_off():
    old = main.settings.PRESENCE_METRICS_ENABLED
    main.settings.PRESENCE_METRICS_ENABLED = True
    try:
        for row in (_session_row(session_mode="AUDIO", camera=True),
                    _session_row(session_mode="VIDEO", camera=False)):
            db = RecordingDB(row)
            r = _client(db).post("/session/presence", json={"session_id": "sid-1", "m1": 0.8})
            assert r.status_code == 200
            assert r.json()["stored"] is False   # no penalty, just not stored
            assert db.updates == []
            _cleanup()
    finally:
        main.settings.PRESENCE_METRICS_ENABLED = old
        _cleanup()


def test_endpoint_response_never_carries_a_band():
    old = main.settings.PRESENCE_METRICS_ENABLED
    main.settings.PRESENCE_METRICS_ENABLED = True
    db = RecordingDB(_session_row())
    try:
        r = _client(db).post("/session/presence", json={"session_id": "sid-1", "m1": 0.8})
        flat = json.dumps(r.json()).lower()
        for forbidden in ("band", "benchmark", "score", "ready"):
            assert forbidden not in flat
    finally:
        main.settings.PRESENCE_METRICS_ENABLED = old
        _cleanup()
