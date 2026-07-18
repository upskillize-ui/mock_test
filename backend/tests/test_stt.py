"""Unit tests for Voice Phase 2 STT (app/stt.py + POST /session/stt).

Covers the hard-rule surface: graceful None on failure (never a dead end),
per-session cost cap, and the endpoint gates — feature flag, BEHAVIOURAL-only
stage restriction, voice_recording consent, and the 10 MB size cap. No real
Sarvam calls — the vendor path is monkeypatched; no real DB — a tiny fake stands
in for the SQLAlchemy session.

Runnable with either:  python -m pytest tests/test_stt.py
                  or:  python tests/test_stt.py
"""
import asyncio
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import stt as s  # noqa: E402
from app.main import app  # noqa: E402
from app.db import get_db  # noqa: E402
from app.auth import current_user  # noqa: E402


# ── stt.transcribe: graceful None on any failure ────────────────────────────

def test_transcribe_none_without_api_key():
    old = s.settings.SARVAM_API_KEY
    s.settings.SARVAM_API_KEY = ""
    try:
        assert asyncio.run(s.transcribe(b"some-audio-bytes", "audio/webm")) is None
    finally:
        s.settings.SARVAM_API_KEY = old


def test_transcribe_none_on_empty_audio():
    old = s.settings.SARVAM_API_KEY
    s.settings.SARVAM_API_KEY = "present"
    try:
        assert asyncio.run(s.transcribe(b"", "audio/webm")) is None
    finally:
        s.settings.SARVAM_API_KEY = old


# ── Response parsing: empty-vs-fail distinction + shape hardening ────────────
# The bug: a Saarika 200 with a blank/unreadable transcript returned None, exactly
# like a real vendor failure, so every "couldn't hear you on real speech" turn logged
# status=fail and was undiagnosable. transcribe_full must now return a dict with
# transcript=None for a 200-but-blank body (-> status=empty) and None ONLY for a real
# failure (-> status=fail).

def test_extract_transcript_flat_and_segmented():
    assert s._extract_transcript({"transcript": "hello there"}) == "hello there"
    assert s._extract_transcript({"text": "  spaced  "}) == "spaced"
    # blank / missing -> None (a genuinely-empty vendor answer)
    assert s._extract_transcript({"transcript": ""}) is None
    assert s._extract_transcript({"request_id": "abc", "transcript": None}) is None
    # segmented / diarized shape carries the text in a list of segments
    seg = {"transcript": "", "diarized_transcript": {"entries": [
        {"transcript": "first part"}, {"transcript": "second part"}]}}
    assert s._extract_transcript(seg) == "first part second part"


def test_transcribe_full_empty_vs_fail():
    orig = s._request
    try:
        # 200 with a blank body -> dict{transcript:None}, NOT None (so status=empty, not fail)
        async def _blank(audio_bytes, mime, want_timestamps):
            return {"request_id": "r1", "transcript": "", "timestamps": None}
        s._request = _blank
        out = asyncio.run(s.transcribe_full(b"audio", "audio/webm"))
        assert out is not None and out["transcript"] is None

        # a real vendor failure (transport/non-200/decode) -> None
        async def _fail(audio_bytes, mime, want_timestamps):
            return None
        s._request = _fail
        assert asyncio.run(s.transcribe_full(b"audio", "audio/webm")) is None
    finally:
        s._request = orig


# ── Per-session cost cap ────────────────────────────────────────────────────

def test_cost_cap_counts_and_trips():
    sid = "sess-cap"
    s._session_stt_counts.pop(sid, None)
    try:
        assert s.stt_cap_reached(sid, 2) is False
        s.note_stt_call(sid)
        assert s.stt_calls_used(sid) == 1
        assert s.stt_cap_reached(sid, 2) is False
        s.note_stt_call(sid)
        assert s.stt_cap_reached(sid, 2) is True   # at the cap -> blocked
    finally:
        s._session_stt_counts.pop(sid, None)


# ── Endpoint gates: fake DB + auth override ─────────────────────────────────

class _Result:
    def __init__(self, row):
        self._row = row
    def mappings(self):
        return self
    def first(self):
        return self._row


class FakeDB:
    """Routes the two queries the endpoint makes by table name."""
    def __init__(self, session_row, has_consent):
        self.session_row = session_row
        self.has_consent = has_consent
    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "vyom_consents" in sql:
            return _Result(1 if self.has_consent else None)
        if "vyom_sessions" in sql:
            return _Result(self.session_row)
        return _Result(None)
    def commit(self):
        pass


def _session_row(stage="BEHAVIOURAL", level="Fresher"):
    return {"id": "sid-1", "user_id": "u1", "current_stage": stage, "level": level,
            "status": "active", "deleted_at": None}


def _client(session_row, has_consent=True):
    app.dependency_overrides[get_db] = lambda: FakeDB(session_row, has_consent)
    app.dependency_overrides[current_user] = lambda: "u1"
    return TestClient(app)


def _cleanup():
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(current_user, None)
    s._session_stt_counts.pop("sid-1", None)


def _post(client, audio=b"fake-audio", ct="audio/webm"):
    return client.post("/session/stt", data={"session_id": "sid-1"},
                       files={"audio": ("answer.webm", audio, ct)})


def _with_flags(stt_enabled, voice_enabled, fn):
    o1, o2 = s.settings.STT_ENABLED, s.settings.VOICE_ENABLED
    s.settings.STT_ENABLED, s.settings.VOICE_ENABLED = stt_enabled, voice_enabled
    # main.settings is the same singleton, but set there too defensively.
    from app import main as m
    m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = stt_enabled, voice_enabled
    try:
        return fn()
    finally:
        s.settings.STT_ENABLED, s.settings.VOICE_ENABLED = o1, o2
        m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = o1, o2


def _fake_transcribe(text="the transcribed answer"):
    async def _f(audio_bytes, mime):
        return text
    return _f


def _fake_transcribe_full(text="the transcribed answer"):
    async def _f(audio_bytes, mime, want_timestamps=True):
        if text is None:
            return None
        return {"transcript": text, "timestamps": None, "confidence": None}
    return _f


def test_endpoint_404_when_feature_off():
    def go():
        client = _client(_session_row())
        r = _post(client)
        assert r.status_code == 404, r.text
    try:
        _with_flags(False, True, go)   # STT off
        _with_flags(True, False, go)   # VOICE off
    finally:
        _cleanup()


def test_endpoint_accepted_in_all_answering_rounds():
    # Phase 3 Part B: the BEHAVIOURAL-only restriction is gone — STT is accepted in
    # every answering round (Warm-up, Domain, Case, Reverse), not a 409.
    orig = s.transcribe_full
    s.transcribe_full = _fake_transcribe_full("domain voice answer")
    def go():
        for stage in ("WARMUP", "DOMAIN", "CASE", "REVERSE"):
            client = _client(_session_row(stage=stage))
            r = _post(client)
            assert r.status_code == 200, f"{stage}: {r.text}"
            assert r.json()["transcript"] == "domain voice answer"
            _cleanup()
    try:
        _with_flags(True, True, go)
    finally:
        s.transcribe_full = orig
        _cleanup()


def test_endpoint_requires_voice_consent():
    def go():
        client = _client(_session_row(), has_consent=False)
        r = _post(client)
        assert r.status_code == 403, r.text
        assert "consent" in r.text.lower()
    try:
        _with_flags(True, True, go)
    finally:
        _cleanup()


def test_endpoint_size_cap():
    def go():
        old = s.settings.STT_MAX_UPLOAD_BYTES
        s.settings.STT_MAX_UPLOAD_BYTES = 10
        from app import main as m
        m.settings.STT_MAX_UPLOAD_BYTES = 10
        try:
            client = _client(_session_row())
            r = _post(client, audio=b"x" * 50)   # 50 bytes > 10-byte cap
            assert r.status_code == 413, r.text
        finally:
            s.settings.STT_MAX_UPLOAD_BYTES = old
            m.settings.STT_MAX_UPLOAD_BYTES = old
    try:
        _with_flags(True, True, go)
    finally:
        _cleanup()


def test_endpoint_cost_cap_429():
    def go():
        # Phase 3: cap is MAX_ANSWERS_PER_SESSION + 5. Pre-fill to the cap.
        s._session_stt_counts["sid-1"] = s.settings.MAX_ANSWERS_PER_SESSION + 5
        client = _client(_session_row(level="Fresher"))
        r = _post(client)
        assert r.status_code == 429, r.text
    try:
        _with_flags(True, True, go)
    finally:
        _cleanup()


def test_endpoint_happy_path_returns_transcript():
    orig = s.transcribe_full
    s.transcribe_full = _fake_transcribe_full("my behavioural answer")
    def go():
        client = _client(_session_row())
        r = _post(client)
        assert r.status_code == 200, r.text
        assert r.json()["transcript"] == "my behavioural answer"
    try:
        _with_flags(True, True, go)
    finally:
        s.transcribe_full = orig
        _cleanup()


def test_endpoint_graceful_null_on_transcribe_failure():
    orig = s.transcribe_full
    s.transcribe_full = _fake_transcribe_full(None)   # vendor failed -> None, never a dead end
    def go():
        client = _client(_session_row())
        r = _post(client)
        assert r.status_code == 200, r.text
        assert r.json()["transcript"] is None
        assert r.json()["delivery_metrics"] is None
    try:
        _with_flags(True, True, go)
    finally:
        s.transcribe_full = orig
        _cleanup()


# ── State signal: stt_available reflects the two flags ──────────────────────

def test_state_stt_available_true_only_when_both_flags_on():
    # QA-02: the flags are necessary but no longer sufficient — the MODE decides whether a
    # mic exists at all, so this test now says which mode it is asking about. A spoken one.
    # (TEXT is covered in test_intake_and_modes.py.)
    from app import main as m
    row = {"level": "Fresher", "current_stage": "BEHAVIOURAL", "round_index": 1,
           "awaiting_rating": 0, "answer_count": 1}
    o1, o2 = m.settings.STT_ENABLED, m.settings.VOICE_ENABLED
    try:
        m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = True, True
        assert m._build_state(row, session_mode="AUDIO").stt_available is True
        m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = True, False
        assert m._build_state(row, session_mode="AUDIO").stt_available is False   # VOICE off
        m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = False, True
        assert m._build_state(row, session_mode="AUDIO").stt_available is False   # STT off
        m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = False, False
        assert m._build_state(row, session_mode="AUDIO").stt_available is False
    finally:
        m.settings.STT_ENABLED, m.settings.VOICE_ENABLED = o1, o2


# ── Decision 1: consent at point of capture — start_session must NOT gate ────
# Regression guard. With VOICE_ENABLED=true and NO voice_recording consent, a
# session must still start normally (typed-only learners are not blocked). Voice
# consent is enforced only at capture (/session/stt), asserted above.

class _StartDB:
    """Permissive fake for the start_session path. Note: it never returns a
    voice_recording consent row — if a start-time consent gate were re-added, the
    gate would read has_consent=False and 403, failing this test."""
    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "session_count FROM vyom_rate_limits" in sql:
            return _Result(SimpleNamespace(session_count=1))   # under the daily cap
        return SimpleNamespace(lastrowid=1,
                               mappings=lambda: _Result(None),
                               first=lambda: None,
                               fetchall=lambda: [])
    def commit(self):
        pass


def test_start_session_does_not_require_voice_consent():
    from app import main as m
    from app import intake as ik
    saved = (ik.get_student_context, m.fetch_alumni_intel, m.call_claude)

    async def _fake_claude(**kwargs):
        return "Hi there! Let's begin your interview."

    # Patch the gather where it RUNS. It lives in app/intake.py now — patching
    # main.get_student_context binds nothing, and this test would still pass, because
    # intake.gather swallows the error and returns {}. Green for the wrong reason is
    # worse than red.
    ik.get_student_context = lambda uid, db: {}
    m.fetch_alumni_intel = lambda db, company, role: ""
    m.call_claude = _fake_claude
    app.dependency_overrides[get_db] = lambda: _StartDB()
    app.dependency_overrides[current_user] = lambda: "u1"

    def go():
        client = TestClient(app)
        r = client.post("/session/start", json={"role": "Software Engineer", "level": "Fresher"})
        # The point: NOT 403 (no voice-consent gate at start), even with voice on.
        assert r.status_code == 200, r.text
        assert r.json().get("session_id")
    try:
        # VOICE_ENABLED on, STT off — the old gate would have 403'd here.
        _with_flags(False, True, go)
    finally:
        ik.get_student_context, m.fetch_alumni_intel, m.call_claude = saved
        _cleanup()


# ── Item 6: live-caption partial endpoint (/session/stt/partial) ────────────
# Same audio path + vendor as /session/stt, but display-only: no metrics, no storage, a
# SEPARATE cost cap, and a null transcript (never an error) when the cap is hit.

def _post_partial(client, audio=b"fake-audio", ct="audio/webm"):
    return client.post("/session/stt/partial", data={"session_id": "sid-1"},
                       files={"audio": ("partial.webm", audio, ct)})


def test_partial_endpoint_transcribes_a_window_without_metrics():
    orig = s.transcribe
    s.transcribe = _fake_transcribe("partial words so far")
    s._session_stt_partial_counts.pop("sid-1", None)
    def go():
        r = _post_partial(_client(_session_row()))
        assert r.status_code == 200, r.text
        assert r.json()["transcript"] == "partial words so far"
        assert r.json().get("delivery_metrics") is None      # display-only, never scored
    try:
        _with_flags(True, True, go)
    finally:
        s.transcribe = orig
        s._session_stt_partial_counts.pop("sid-1", None)
        _cleanup()


def test_partial_endpoint_gated_by_feature_and_consent():
    orig = s.transcribe
    s.transcribe = _fake_transcribe("x")
    def off():
        assert _post_partial(_client(_session_row())).status_code == 404
    def noconsent():
        assert _post_partial(_client(_session_row(), has_consent=False)).status_code == 403
    try:
        _with_flags(False, True, off); _cleanup()
        _with_flags(True, True, noconsent)
    finally:
        s.transcribe = orig
        _cleanup()


def test_partial_cap_is_separate_and_stops_without_erroring():
    orig = s.transcribe
    s.transcribe = _fake_transcribe("y")
    s._session_stt_partial_counts.pop("sid-1", None)
    from app import main as m
    o_cap = m.settings.STT_PARTIAL_MAX_PER_SESSION
    m.settings.STT_PARTIAL_MAX_PER_SESSION = 1
    def go():
        assert _post_partial(_client(_session_row())).json()["transcript"] == "y"   # first: ok
        _cleanup()
        # Cap reached -> null transcript (caption simply stops growing), NOT an error...
        r = _post_partial(_client(_session_row()))
        assert r.status_code == 200 and r.json()["transcript"] is None
        # ...and the ANSWER STT allowance is completely untouched by caption partials.
        assert s.stt_calls_used("sid-1") == 0
    try:
        _with_flags(True, True, go)
    finally:
        s.transcribe = orig
        m.settings.STT_PARTIAL_MAX_PER_SESSION = o_cap
        s._session_stt_partial_counts.pop("sid-1", None)
        _cleanup()


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
