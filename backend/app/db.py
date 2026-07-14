from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import json
import logging

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