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
    ("008_student_memory", "vyom_student_memory", None),
    ("008_student_memory", "vyom_sessions", "experience_feedback"),
    # 009 — how the student answered. `session_mode` is NOT `mode` (that one is the
    # feedback style, interview|coach). Without these two columns the mode selector still
    # renders and the session still runs; it is simply never recorded how it was answered,
    # and the benchmark loses its mode factor.
    ("009_intake_and_modes", "vyom_sessions", "session_mode"),
    ("009_intake_and_modes", "vyom_messages", "input_channel"),
    # 010 — Phase D presence metrics m1–m8, a single session-level aggregate. Written
    # only when PRESENCE_METRICS_ENABLED is true (dark until legal sign-off), and read
    # defensively — without the column the readout simply shows the "No presence data"
    # line and no score changes. Report-only; it never enters a benchmark or a band.
    ("010_presence_metrics", "vyom_sessions", "presence_metrics"),
    # 011 — the per-session cost ledger (Capacity/Cost phase). Permanent product telemetry:
    # every completed/abandoned session stores its LLM $ + Sarvam credit breakdown here.
    # Written defensively from _finalize_session — without the column a session still closes
    # normally, it just closes without a stored ledger (and the in-process meters are lost).
    ("011_cost_ledger", "vyom_sessions", "cost_ledger"),
]

# The newest migration the code expects. Reported at boot so a deploy can be eyeballed in
# one line: "schema: up to date (through migration 006_interview_room)".
LATEST_MIGRATION = EXPECTED[-1][0]


# ── The LMS half — TABLES WE READ BUT DO NOT OWN ─────────────────────────────
# Everything above is ours: we wrote the migration, and a missing column means a human
# forgot to run it. Everything HERE belongs to the LMS team. They may rename, move or
# reshape these at any time, legitimately, without telling us — and when they do, it is
# not "drift" and there is no migration of ours to run. It is a dependency that moved.
#
# WHY THIS LIST EXISTS AT ALL:
#   `get_student_context` read `student_profiles`, `student_ai_profiles` and a direct
#   `enrollments.student_id = user_id` join. The first was deleted, the second renamed to
#   `ai_profiles`, and the third was never a user id (it is a `students.id`). All three
#   reads sat inside try/except at log.debug. So the gather returned a dict of Nones, the
#   interviewer opened every session knowing nothing but a first name, the ice-breaker
#   skipped its beat every single time — and NOTHING said so. The features were not
#   broken loudly; they were absent quietly, which is worse, and it lasted weeks.
#   `EXPECTED` could never have caught it: _read_schema only ever looked at `vyom_%`.
#
# THE RULE (and it is the TTS seatbelt's rule, applied to a database):
#   WARN LOUDLY, DEGRADE GRACEFULLY, NEVER BLOCK. The Space does not refuse to boot over
#   a dependency it does not own. A missing LMS column costs us a richer opening; it must
#   never cost a student their session. Every read of these is defensive at the call site
#   and stays that way — this list exists so the degradation is ANNOUNCED, not silent.
#
# (table, column)  — column=None means "the TABLE itself must exist".
LMS_EXPECTED: list[tuple[str, str | None]] = [
    # Identity, education, work history, résumé, psychometrics — and the ice-breaker's
    # only two safe personal facts. These columns used to live on `student_profiles`.
    ("users", "full_name"),
    ("users", "city"),
    ("users", "hobbies"),
    ("users", "education_level"),
    ("users", "institution"),
    ("users", "graduation_year"),
    ("users", "field_of_study"),
    ("users", "work_experience_years"),
    ("users", "current_employer"),
    ("users", "current_designation"),
    ("users", "skills"),
    ("users", "resume_url"),
    ("users", "psycho_result"),
    # ProfileIQ. `student_id` is a users.id despite the name — verified against
    # student_email on every row that joins. Formerly `student_ai_profiles`.
    ("ai_profiles", "student_id"),
    ("ai_profiles", "professional_summary"),
    ("ai_profiles", "status"),
    # The middle hop the old enrollments query skipped: users.id → students.user_id →
    # students.id → enrollments.student_id. Without `students`, courses cannot be read.
    ("students", "user_id"),
    ("enrollments", "student_id"),
    ("enrollments", "course_id"),
    ("courses", "course_name"),
    ("certificates", "student_id"),
]


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


def missing_lms_objects(tables: set[str], columns: set[tuple[str, str]]) -> list[tuple[str, str | None]]:
    """Which LMS-owned objects we read are absent. PURE, like missing_objects.

    Deliberately returns a DIFFERENT shape: there is no migration column, because there is
    no migration. Nothing we can write fixes a table the LMS team moved — the only honest
    outputs are a warning and a degraded gather.
    """
    missing = []
    for table, column in LMS_EXPECTED:
        if table not in tables:
            missing.append((table, column))
        elif column is not None and (table, column) not in columns:
            missing.append((table, column))
    return missing


def _read_schema(db) -> tuple[set[str], set[tuple[str, str]]]:
    """Every table and column we care about in the CURRENT database. Two reads, no writes,
    no DDL.

    This used to filter `LIKE 'vyom\\_%'`, and that filter was load-bearing in the worst
    way: the LMS tables we depend on were structurally invisible to the only thing built to
    notice a schema moving. It now reads our tables AND the LMS tables named in
    LMS_EXPECTED, so both halves can be checked. Still two queries — the LMS names are
    bound as a parameter list rather than fetched by a second round trip.
    """
    lms_tables = sorted({t for t, _c in LMS_EXPECTED})
    params = {f"t{i}": name for i, name in enumerate(lms_tables)}
    in_list = ", ".join(f":{k}" for k in params)

    tables = {
        r[0] for r in db.execute(text(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() "
            f"AND (TABLE_NAME LIKE 'vyom\\_%' OR TABLE_NAME IN ({in_list}))"
        ), params)
    }
    columns = {
        (r[0], r[1]) for r in db.execute(text(
            "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            f"AND (TABLE_NAME LIKE 'vyom\\_%' OR TABLE_NAME IN ({in_list}))"
        ), params)
    }
    return tables, columns


def _report_lms(missing: list[tuple[str, str | None]]) -> None:
    """The LMS banner. WARNING, not ERROR: nothing here is a deploy's fault, nothing here
    is fixable by running a file, and nothing here may stop the app from serving.
    """
    if not missing:
        log.info("lms schema: all %d expected object(s) present", len(LMS_EXPECTED))
        return

    log.warning("=" * 78)
    log.warning("LMS SCHEMA MOVED — %d object(s) we read are not there.", len(missing))
    log.warning("")
    for table, column in missing:
        what = f"{table}.{column}" if column else f"{table}  (TABLE)"
        log.warning("    MISSING  %s", what)
    log.warning("")
    log.warning("These tables belong to the LMS team, not to us. There is NO migration to")
    log.warning("run — if they moved something, this is the announcement, and the fix is a")
    log.warning("conversation with them plus a change to app/db.get_student_context.")
    log.warning("")
    log.warning("The interview still runs. get_student_context degrades field by field, so")
    log.warning("the cost is a thinner opening (a skipped ice-breaker, no course history),")
    log.warning("never a failed session. This warning exists because the LAST time these")
    log.warning("moved, nothing said so for weeks.")
    log.warning("=" * 78)


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

    # The LMS half first, and on its own terms: it is reported, never returned. Folding it
    # into the return value would put a table we cannot migrate onto a list captioned "run,
    # in order" — an instruction nobody could follow.
    try:
        _report_lms(missing_lms_objects(tables, columns))
    except Exception as e:  # a bug in OUR reporting must not cost the migration check
        log.warning("lms schema check skipped: %s", type(e).__name__)

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
