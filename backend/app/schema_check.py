"""Schema drift check — run once at boot, LOUD when the database is behind the code.

WHY THIS EXISTS
Every optional column in this codebase is written defensively:

    try:
        db.execute(text("UPDATE vyom_sessions SET camera_at_join=1 ..."))
    except Exception:
        log.warning("camera_at_join not stored (apply migration 006?)")

That is the right call at the point of use — a missing column must never break a live
interview. But it has a nasty second-order effect: the app runs perfectly happily on a
database that is two migrations behind, quietly doing less than it says it does. That is
exactly what happened here. Migrations 004 and 006 had NEVER been applied to the dev
database, so the founder's UAT session ran with no roster-name persistence, no camera
policy, and no early-wrap reason — and the only trace was a warning line per request,
buried in a log nobody was reading, at the moment the feature silently didn't happen.

So: probe the schema once, at boot, and say so plainly. One banner, at startup, naming the
migration file to run.

WHAT IT DOES NOT DO
It NEVER applies anything. Not a column, not a table, not "just this one, it's additive".
A process that mutates a shared schema on boot is how two app instances race each other
into a half-migrated database at 3am. It reports; a human runs the migration.

It also never blocks boot. A drifted database still serves — every call site degrades
gracefully, which is the whole point of the defensive writes. A schema check that could
take the app down would be a worse bug than the one it is warning about.
"""

import logging

from sqlalchemy import text

log = logging.getLogger(__name__)


# The schema surface this code EXPECTS, newest migration last. Add a row here in the same
# commit that adds a column — that is the whole contract, and it is why this file is a flat
# list and not something clever.
#
# (migration, table, column)   — column=None means "the TABLE itself must exist".
EXPECTED: list[tuple[str, str, str | None]] = [
    ("001_security_and_history", "vyom_sessions", "completion_type"),
    ("002_spec_alignment", "vyom_answer_ratings", None),
    ("003_dpdpa_foundation", "vyom_consents", None),
    ("004_delivery_metrics", "vyom_messages", "delivery_metrics"),
    ("005_interviewer_identity", "vyom_sessions", "interviewer_identity"),
    ("006_interview_room", "vyom_focus_events", None),
    ("006_interview_room", "vyom_messages", "presence_metrics"),
    ("006_interview_room", "vyom_sessions", "interviewer_name"),
    ("006_interview_room", "vyom_sessions", "early_wrap_reason"),
    ("006_interview_room", "vyom_sessions", "early_wrap_stage"),
    ("006_interview_room", "vyom_sessions", "camera_at_join"),
    ("007_scoring_context", "vyom_debriefs", "benchmark"),
    ("007_scoring_context", "vyom_debriefs", "benchmark_uncapped"),
    ("007_scoring_context", "vyom_debriefs", "score_factors"),
    ("007_scoring_context", "vyom_debriefs", "weights_version"),
    ("007_scoring_context", "vyom_debriefs", "gated_band"),
    ("007_scoring_context", "vyom_debriefs", "substantive_answers"),
    ("007_scoring_context", "vyom_debriefs", "scored"),
]

# The newest migration the code expects. Reported at boot so a deploy can be eyeballed in
# one line: "schema: up to date (through migration 006_interview_room)".
LATEST_MIGRATION = EXPECTED[-1][0]


def missing_objects(tables: set[str], columns: set[tuple[str, str]]) -> list[tuple[str, str, str | None]]:
    """Which expected objects are absent. PURE — the DB round trip is the caller's job, so
    the interesting half of this is testable without a database.

    `tables`  : {"vyom_sessions", ...}
    `columns` : {("vyom_sessions", "camera_at_join"), ...}
    """
    missing = []
    for migration, table, column in EXPECTED:
        if table not in tables:
            missing.append((migration, table, column))
        elif column is not None and (table, column) not in columns:
            missing.append((migration, table, column))
    return missing


def pending_migrations(missing: list[tuple[str, str, str | None]]) -> list[str]:
    """The migration FILES a human needs to run, in order, de-duplicated."""
    out: list[str] = []
    for migration, _table, _column in missing:
        if migration not in out:
            out.append(migration)
    return out


def _read_schema(db) -> tuple[set[str], set[tuple[str, str]]]:
    """Every vyom_ table and column in the CURRENT database. Two reads, no writes, no DDL."""
    tables = {
        r[0] for r in db.execute(text(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'vyom\\_%'"
        ))
    }
    columns = {
        (r[0], r[1]) for r in db.execute(text(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'vyom\\_%'"
        ))
    }
    return tables, columns


def check(db) -> list[str]:
    """Probe the live schema and LOG THE RESULT. Returns the pending migration files ([] =
    up to date). Never raises, never writes, never blocks boot.

    An unreachable database here is NOT a drift finding — it is a database problem, and
    /health already reports it. We say we could not check, and get out of the way.
    """
    try:
        tables, columns = _read_schema(db)
    except Exception as e:
        log.warning("schema check skipped (could not read information_schema): %s",
                    type(e).__name__)
        return []

    missing = missing_objects(tables, columns)
    if not missing:
        log.info("schema: up to date (through migration %s)", LATEST_MIGRATION)
        return []

    pending = pending_migrations(missing)

    # Loud, and specific enough to act on without opening the code. This is the banner the
    # last four weeks of silent degradation needed.
    log.error("=" * 78)
    log.error("SCHEMA DRIFT — THE DATABASE IS BEHIND THE CODE. %d expected object(s) missing.",
              len(missing))
    log.error("")
    for migration, table, column in missing:
        what = f"{table}.{column}" if column else f"{table}  (TABLE)"
        log.error("    MISSING  %-42s  needs migration %s", what, migration)
    log.error("")
    log.error("The app WILL still serve: every one of these is written defensively and")
    log.error("degrades to a no-op. That is the danger — the features above are silently")
    log.error("NOT HAPPENING, and the only other trace is a warning per request.")
    log.error("")
    log.error("Run, in order:")
    for m in pending:
        log.error("    mysql ... < db/migration_%s.sql", m)
    log.error("=" * 78)
    return pending
