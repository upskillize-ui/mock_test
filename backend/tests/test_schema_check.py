"""SCHEMA DRIFT — the database quietly falling behind the code.

This check exists because of a real, measured failure, not a hypothetical one. Migrations
004 and 006 had NEVER been applied to the dev database. The app ran perfectly happily: every
optional column is written defensively (try/except -> log a warning -> carry on), so nothing
crashed and nothing 500'd. What actually happened was that roster-name persistence, the
camera policy and early-wrap reasons silently did not happen — through an entire founder UAT
session — and the only trace was one warning line per request, in a log nobody was reading.

Defensive writes are right at the point of use. They are catastrophic as a deployment story.
So the schema is probed once at boot and the drift is shouted about.

Runnable with:  python -m pytest tests/test_schema_check.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging  # noqa: E402
from pathlib import Path  # noqa: E402

from app import schema_check as sc  # noqa: E402
from app.schemas import HealthResponse  # noqa: E402


def _full_schema():
    """A database that is completely up to date."""
    tables = {t for _m, t, _c in sc.EXPECTED}
    columns = {(t, c) for _m, t, c in sc.EXPECTED if c is not None}
    return tables, columns


# ── The happy path ───────────────────────────────────────────────────────────

def test_an_up_to_date_database_reports_nothing():
    tables, columns = _full_schema()
    assert sc.missing_objects(tables, columns) == []
    assert sc.pending_migrations([]) == []


# ── The exact failure that prompted this ─────────────────────────────────────

def test_the_real_drift_that_went_unnoticed_for_a_whole_uat_session():
    """The dev database as it ACTUALLY was: 005 applied, 004 and 006 never run. Every
    feature behind those columns was a silent no-op, and the app looked completely fine."""
    tables, columns = _full_schema()
    tables.discard("vyom_focus_events")
    for col in ("delivery_metrics", "presence_metrics"):
        columns.discard(("vyom_messages", col))
    for col in ("interviewer_name", "early_wrap_reason", "early_wrap_stage", "camera_at_join"):
        columns.discard(("vyom_sessions", col))

    missing = sc.missing_objects(tables, columns)
    pending = sc.pending_migrations(missing)

    assert pending == ["004_delivery_metrics", "006_interview_room"]
    # 005 WAS applied, and must not be dragged back in.
    assert not any(m.startswith("005") for m in pending)
    # Every missing object is named, so nobody has to go and diff a schema by hand.
    names = {(t, c) for _m, t, c in missing}
    assert ("vyom_sessions", "camera_at_join") in names
    assert ("vyom_focus_events", None) in names


def test_a_missing_table_is_caught_as_well_as_a_missing_column():
    tables, columns = _full_schema()
    tables.discard("vyom_focus_events")
    missing = sc.missing_objects(tables, columns)
    assert ("006_interview_room", "vyom_focus_events", None) in missing


def test_a_missing_table_does_not_also_report_every_column_on_it():
    """A dropped table should read as ONE finding, not a wall of noise about its columns."""
    tables, columns = _full_schema()
    tables.discard("vyom_messages")
    columns = {(t, c) for (t, c) in columns if t != "vyom_messages"}
    missing = sc.missing_objects(tables, columns)
    assert [m for m in missing if m[1] == "vyom_messages"] == [
        ("004_delivery_metrics", "vyom_messages", "delivery_metrics"),
        ("006_interview_room", "vyom_messages", "presence_metrics"),
    ]


def test_pending_migrations_are_ordered_and_deduplicated():
    """Six missing columns from one migration is ONE migration to run, and the order is the
    order they must be applied in — 006 depends on 004's column existing."""
    tables, columns = _full_schema()
    for col in ("interviewer_name", "early_wrap_reason", "early_wrap_stage", "camera_at_join"):
        columns.discard(("vyom_sessions", col))
    pending = sc.pending_migrations(sc.missing_objects(tables, columns))
    assert pending == ["006_interview_room"]


# ── It NEVER applies anything, and NEVER blocks boot ─────────────────────────

def test_the_check_never_writes_anything():
    """A process that mutates a shared schema on boot is how two app instances race each
    other into a half-migrated database. It reports; a human runs the migration."""
    source = Path(sc.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]        # ignore the module docstring
    for forbidden in ("ALTER ", "CREATE ", "DROP ", "INSERT ", "UPDATE ", "DELETE "):
        assert forbidden not in body.upper(), forbidden
    assert "SELECT" in body.upper()          # ...it only ever reads


def test_an_unreachable_database_is_not_a_drift_finding(caplog):
    """A database that cannot be read is a DATABASE problem — /health already says so. The
    schema check must not cry drift about it, and must not take the app down."""
    class Dead:
        def execute(self, *a, **k):
            raise RuntimeError("connection refused")

    with caplog.at_level(logging.WARNING):
        assert sc.check(Dead()) == []
    assert "schema check skipped" in caplog.text


def test_drift_is_logged_loudly_and_names_the_file_to_run(caplog):
    tables, columns = _full_schema()
    columns.discard(("vyom_sessions", "camera_at_join"))

    class Fake:
        def __init__(self):
            self.n = 0

        def execute(self, *a, **k):
            self.n += 1
            return [(t,) for t in tables] if self.n == 1 else list(columns)

    with caplog.at_level(logging.ERROR):
        pending = sc.check(Fake())

    assert pending == ["006_interview_room"]
    assert "SCHEMA DRIFT" in caplog.text
    assert "camera_at_join" in caplog.text
    # It must be actionable without opening the source.
    assert "db/migration_006_interview_room.sql" in caplog.text
    # ...and honest about WHY this is dangerous rather than merely untidy.
    assert "still serve" in caplog.text


def test_an_up_to_date_database_says_so_at_boot(caplog):
    tables, columns = _full_schema()

    class Fake:
        def __init__(self):
            self.n = 0

        def execute(self, *a, **k):
            self.n += 1
            return [(t,) for t in tables] if self.n == 1 else list(columns)

    with caplog.at_level(logging.INFO):
        assert sc.check(Fake()) == []
    assert "schema: up to date" in caplog.text
    assert sc.LATEST_MIGRATION in caplog.text


# ── The manifest tracks the migrations that actually exist ───────────────────

def test_every_expected_migration_has_a_file_on_disk():
    """The manifest is a flat list on purpose, and this is what keeps it honest: a row
    naming a migration that does not exist would send someone hunting for a missing file."""
    db_dir = Path(__file__).resolve().parent.parent.parent / "db"
    for migration, _t, _c in sc.EXPECTED:
        f = db_dir / f"migration_{migration}.sql"
        assert f.exists(), f"{f.name} named in EXPECTED but not on disk"


def test_the_newest_migration_is_the_one_the_code_needs():
    assert sc.LATEST_MIGRATION == "008_student_memory"
    assert sc.EXPECTED[-1][0] == sc.LATEST_MIGRATION


# ── /health carries it, so a deploy can see drift without reading a log ──────

def test_health_reports_drift_without_calling_the_service_unhealthy():
    """A drifted database still serves every request — the service is UP, it is just quietly
    doing less than it says. Failing the health check over it would take down a working app."""
    h = HealthResponse(status="ok", db="ok", schema_status="drift",
                       pending_migrations=["006_interview_room"],
                       model_interview="m", model_debrief="d")
    assert h.status == "ok"
    assert h.schema_status == "drift"
    assert h.pending_migrations == ["006_interview_room"]


def test_health_defaults_to_ok_so_the_field_is_always_present():
    h = HealthResponse(status="ok", db="ok", model_interview="m", model_debrief="d")
    assert h.schema_status == "ok"
    assert h.pending_migrations == []


# ── The LMS half — tables we read but do not own ─────────────────────────────
# These tests exist because of a second, worse instance of the same disease. The vyom_
# check above was already in place and still could not see it: `get_student_context` read
# `student_profiles` (deleted), `student_ai_profiles` (renamed to `ai_profiles`) and joined
# `enrollments.student_id` straight to a user id (it is a `students.id` — 0 of 10 rows ever
# matched). Every read degraded at log.debug, so for weeks the interviewer opened sessions
# knowing a first name and nothing else, and the ice-breaker skipped its beat every time.
# _read_schema filtered `LIKE 'vyom\_%'`, so the only thing built to notice a schema moving
# was structurally blind to it.


def _full_lms():
    """An LMS database that has everything we read."""
    tables = {t for t, _c in sc.LMS_EXPECTED}
    columns = {(t, c) for t, c in sc.LMS_EXPECTED if c is not None}
    return tables, columns


def test_nothing_missing_when_the_lms_has_everything_we_read():
    tables, columns = _full_lms()
    assert sc.missing_lms_objects(tables, columns) == []


def test_a_renamed_lms_table_is_reported():
    """The exact drift that actually happened: student_ai_profiles -> ai_profiles."""
    tables, columns = _full_lms()
    tables.discard("ai_profiles")
    missing = sc.missing_lms_objects(tables, columns)
    assert ("ai_profiles", "professional_summary") in missing


def test_a_dropped_lms_column_is_reported():
    tables, columns = _full_lms()
    columns.discard(("users", "city"))
    assert ("users", "city") in sc.missing_lms_objects(tables, columns)


def test_the_ice_breakers_two_facts_are_watched():
    """city and hobbies are the ONLY safe personal facts the opening may use. If either
    silently vanishes the beat goes back to skipping every time — which is precisely the
    failure this whole list exists to announce."""
    watched = {(t, c) for t, c in sc.LMS_EXPECTED}
    assert ("users", "city") in watched
    assert ("users", "hobbies") in watched


def test_the_enrollments_chain_is_watched_including_the_hop_that_was_skipped():
    """users.id -> students.user_id -> students.id -> enrollments.student_id. `students` is
    the hop the old query skipped, so it is the one most worth watching."""
    watched = {(t, c) for t, c in sc.LMS_EXPECTED}
    assert ("students", "user_id") in watched
    assert ("enrollments", "student_id") in watched


def test_lms_drift_never_becomes_a_pending_migration():
    """THE contract. `pending_migrations` captions its output "run, in order" — putting a
    table we cannot migrate on that list would be an instruction nobody could follow.
    LMS findings are a different shape for exactly this reason, and they are reported,
    never returned."""
    tables, columns = _full_schema()
    lms_t, lms_c = _full_lms()
    lms_t.discard("ai_profiles")          # the LMS moved something...
    tables |= lms_t
    columns |= lms_c

    class Fake:
        def __init__(self):
            self.n = 0

        def execute(self, *a, **k):
            self.n += 1
            return [(t,) for t in tables] if self.n == 1 else list(columns)

    # ...and our own migrations are fine, so there is nothing for a human to run.
    assert sc.check(Fake()) == []


def test_lms_drift_warns_but_never_blocks_boot(caplog):
    """Same philosophy as the TTS seatbelt: the Space never refuses to boot over a
    dependency it does not own. Warn loudly, degrade gracefully, keep serving."""
    tables, columns = _full_lms()
    tables.discard("students")
    with caplog.at_level(logging.WARNING):
        sc._report_lms(sc.missing_lms_objects(tables, columns))
    assert "LMS SCHEMA MOVED" in caplog.text
    assert "There is NO migration to" in caplog.text
    assert "The interview still runs" in caplog.text
    # Warning, not error: nothing here is a deploy's fault or a deploy's fix.
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_the_lms_read_is_no_longer_blind_to_non_vyom_tables():
    """The regression guard for the root cause. If someone re-narrows _read_schema to
    `vyom_%`, the LMS half silently reports everything missing forever.

    The table names ride as BOUND PARAMETERS, not as literals in the SQL, so this asserts
    on what was bound — checking the query string would pass a narrowed read by accident.
    """
    seen = []

    class Fake:
        def execute(self, q, params=None, *a, **k):
            seen.append((str(q), params or {}))
            return []

    sc._read_schema(Fake())
    assert len(seen) == 2, "two reads, no more: tables then columns"

    for sql, params in seen:
        bound = set((params or {}).values())
        assert "users" in bound and "ai_profiles" in bound, \
            "_read_schema must ask about LMS tables, not just vyom_ ones"
        assert "vyom\\_%" in sql, "and it must still ask about ours"
        # Every LMS table we depend on is bound, not just the two spot-checked above.
        assert {t for t, _c in sc.LMS_EXPECTED} == bound
