from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import hashlib
import json
import logging
import re

from .config import settings

log = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=280,
    pool_size=5,
    max_overflow=10,
    # An EXPLICIT connect timeout, rather than whatever the driver happens to default to.
    # The boot-time schema check (app.schema_check) opens a connection during the ASGI
    # lifespan — i.e. before the server accepts its first request — so an unreachable
    # database must fail FAST and bounded rather than sitting on a TCP connect while a
    # Hugging Face Space waits to become healthy. Ten seconds, then the check logs
    # "skipped" and the app comes up anyway.
    connect_args={"connect_timeout": 10},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def like_escape(s: str) -> str:
    if not s:
        return ""
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def fetch_alumni_intel(db: Session, company: str, role: str, limit: int = 6) -> str:
    if not company:
        return ""
    try:
        rows = db.execute(
            text(r"""
                SELECT question, round_type, city, interview_date
                FROM vyom_alumni_questions
                WHERE verified = 1
                  AND company LIKE :company ESCAPE '\\'
                  AND role LIKE :role ESCAPE '\\'
                  AND (interview_date IS NULL OR interview_date >= DATE_SUB(CURDATE(), INTERVAL 180 DAY))
                ORDER BY interview_date DESC
                LIMIT :limit
            """),
            {"company": like_escape(company), "role": like_escape(role), "limit": limit},
        ).fetchall()
    except Exception as e:
        log.warning("fetch_alumni_intel failed: %s", e)
        return ""

    if not rows:
        return ""

    lines = [
        f"- [{r.round_type or 'General'}] {r.question}"
        + (f"  (asked in {r.city})" if r.city else "")
        for r in rows
    ]
    return (
        "\n\nRECENT REAL QUESTIONS FROM UPSKILLIZE ALUMNI WHO INTERVIEWED AT "
        f"{company.upper()} FOR {role.upper()} "
        f"(use naturally during the interview — do NOT list them to the learner):\n"
        + "\n".join(lines)
    )


# ── Student memory (migration 008): the variety engine ───────────────────────
# The closed set of memory kinds, enforced HERE rather than by a database ENUM, so that
# Flagship can add a memory type without a migration. See migration_008 for the why.
MEMORY_KIND_OPENING = "opening"
MEMORY_KIND_CLOSING = "closing"
MEMORY_KIND_CHECKIN = "checkin"
MEMORY_KIND_REASK = "reask"
MEMORY_KIND_ENCOURAGEMENT = "encouragement"
MEMORY_KINDS = frozenset({
    MEMORY_KIND_OPENING,
    MEMORY_KIND_CLOSING,
    MEMORY_KIND_CHECKIN,
    MEMORY_KIND_REASK,
    MEMORY_KIND_ENCOURAGEMENT,
})

_MEMORY_NOISE_RX = re.compile(r"[^a-z0-9\s]+")
_MEMORY_WS_RX = re.compile(r"\s+")


def normalize_line(text_in: str) -> str:
    """Casefold, strip punctuation, collapse whitespace.

    The unit of comparison for "has this student heard this before?". Without it,
    "Good morning, Asha!" and "Good morning Asha." are two different memories and the
    student hears the same greeting twice — the exact failure the table exists to stop.
    """
    return _MEMORY_WS_RX.sub(" ", _MEMORY_NOISE_RX.sub(" ", (text_in or "").lower())).strip()


def line_digest(text_in: str) -> str:
    """Content address of a normalised line. Indexable; TEXT is not (see migration 008)."""
    return hashlib.sha256(normalize_line(text_in).encode("utf-8")).hexdigest()


def remember_line(db: Session, user_id: str, session_id: str | None, kind: str,
                  content: str, meta: dict | None = None) -> bool:
    """Record one thing this student HEARD. Returns True if stored.

    DEFENSIVE BY CONSTRUCTION, like every other optional-column write in this codebase:
    a missing table (migration 008 not applied) must never break a live interview. The
    cost of failing here is that the interviewer might repeat itself in six months. The
    cost of raising here is that the candidate's session dies at the greeting. Those are
    not close, so this swallows everything and says so in the log.
    """
    if not user_id or not content or not content.strip():
        return False
    if kind not in MEMORY_KINDS:
        # A typo'd kind writes a row nothing will ever read back — silent and useless.
        # Loud instead: this is a programming error, not a runtime condition.
        log.warning("refusing to store unknown memory kind %r (see db.MEMORY_KINDS)", kind)
        return False
    try:
        db.execute(
            text("""
                INSERT INTO vyom_student_memory
                    (user_id, session_id, kind, content, content_digest, meta)
                VALUES (:uid, :sid, :kind, :content, :digest, :meta)
            """),
            {
                "uid": user_id,
                "sid": session_id,
                "kind": kind,
                "content": content.strip(),
                "digest": line_digest(content),
                "meta": json.dumps(meta) if meta else None,
            },
        )
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        log.warning("memory not stored (apply migration 008?): %s", type(e).__name__)
        return False


def recent_lines(db: Session, user_id: str, kind: str, limit: int = 5) -> list[str]:
    """The last `limit` lines of `kind` this student heard, newest first.

    Read on the kickoff path, so it is bounded and indexed (idx_memory_user_kind_recent
    serves both the WHERE and the ORDER BY). Returns [] on ANY failure — a variety engine
    that cannot read its history degrades to "improvise blind", which is exactly the
    behaviour we had before this table existed.
    """
    if not user_id or kind not in MEMORY_KINDS:
        return []
    try:
        rows = db.execute(
            text("""
                SELECT content FROM vyom_student_memory
                WHERE user_id = :uid AND kind = :kind
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
            """),
            {"uid": user_id, "kind": kind, "limit": int(limit)},
        ).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        log.warning("memory not read (apply migration 008?): %s", type(e).__name__)
        return []


def get_student_context(user_id: str, db: Session) -> dict:
    result = {
        "name": None,
        "ai_profile": None,
        "enrollments": [],
        "education": None,
        "current_status": None,
        "current_role": None,
        "employer": None,
        "skills": None,
        "resume_url": None,
        "psycho": None,
        "source": [],
    }

    try:
        user = db.execute(
            text("SELECT full_name FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
        if user and user.full_name:
            result["name"] = user.full_name
    except Exception as e:
        log.warning("ctx.user failed for uid=%s: %s", user_id, e)

    try:
        ai = db.execute(
            text("""
                SELECT ai_profile_text, ai_profile_json
                FROM student_ai_profiles
                WHERE user_id = :uid
                ORDER BY created_at DESC LIMIT 1
            """),
            {"uid": user_id},
        ).fetchone()
        if ai and (ai.ai_profile_text or ai.ai_profile_json):
            result["ai_profile"] = ai.ai_profile_text or ai.ai_profile_json
            result["source"].append("ai_enhancer")
    except Exception as e:
        log.debug("ctx.ai_profile skipped: %s", e)

    try:
        enrollments = db.execute(
            text("""
                SELECT c.course_name, e.progress_percentage,
                       cert.id AS has_cert
                FROM enrollments e
                JOIN courses c ON e.course_id = c.id
                LEFT JOIN certificates cert
                    ON cert.student_id = e.student_id
                    AND cert.course_id = c.id
                WHERE e.student_id = :uid
                ORDER BY e.created_at DESC
                LIMIT 6
            """),
            {"uid": user_id},
        ).fetchall()
        if enrollments:
            result["enrollments"] = [
                {
                    "course": r.course_name,
                    "progress": r.progress_percentage or 0,
                    "certified": bool(r.has_cert),
                }
                for r in enrollments
            ]
            result["source"].append("enrollments")
    except Exception as e:
        log.debug("ctx.enrollments skipped: %s", e)

    try:
        profile = db.execute(
            text("""
                SELECT education_level, institution, graduation_year,
                       field_of_study, work_experience_years,
                       current_employer, current_designation,
                       skills, resume_url
                FROM student_profiles
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        ).fetchone()

        if profile:
            edu_parts = [
                profile.education_level,
                profile.field_of_study,
                profile.institution,
                str(profile.graduation_year) if profile.graduation_year else None,
            ]
            edu = " · ".join([x for x in edu_parts if x])
            if edu.strip(" ·"):
                result["education"] = edu
                result["source"].append("education")

            yrs = (profile.work_experience_years or "").lower()
            if yrs in ["fresher", "< 1 year", "", "none"]:
                result["current_status"] = "student_or_fresher"
            else:
                result["current_status"] = "working_professional"

            if profile.current_designation or profile.current_employer:
                result["current_role"] = profile.current_designation
                result["employer"] = profile.current_employer
                result["source"].append("work_profile")

            if profile.skills:
                result["skills"] = profile.skills

            if profile.resume_url:
                result["resume_url"] = profile.resume_url
    except Exception as e:
        log.debug("ctx.profile skipped: %s", e)

    try:
        psycho = db.execute(
            text("SELECT psycho_result FROM student_profiles WHERE user_id = :uid"),
            {"uid": user_id},
        ).fetchone()
        if psycho and psycho.psycho_result:
            raw = psycho.psycho_result
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    pass
            if isinstance(raw, dict):
                result["psycho"] = {
                    "type": raw.get("type", ""),
                    "top": raw.get("topDimensions", [])[:3],
                    "desc": raw.get("desc", ""),
                }
                result["source"].append("psychometric")
    except Exception as e:
        log.debug("ctx.psycho skipped: %s", e)

    return result