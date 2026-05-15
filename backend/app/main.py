import json
import logging
import uuid
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, get_student_context, fetch_alumni_intel, like_escape
from .auth import current_user
from .schemas import (
    StartSessionRequest, StartSessionResponse,
    TurnRequest, TurnResponse,
    EndRequest, DebriefResponse,
    AlumniQuestionSubmit, HealthResponse,
    HistoryListResponse, HistoryListItem, HistoryDetailResponse,
)
from .prompts import build_system_prompt, DEBRIEF_INSTRUCTION
from .claude_client import call_claude, extract_resume_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


app = FastAPI(title="InterviewIQ API", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


def _check_rate_limit(db: Session, user_id: str) -> None:
    today = date.today()
    db.execute(
        text("""
            INSERT INTO vyom_rate_limits (user_id, day, session_count)
            VALUES (:u, :d, 1)
            ON DUPLICATE KEY UPDATE session_count = session_count + 1
        """),
        {"u": user_id, "d": today},
    )
    db.commit()
    row = db.execute(
        text("SELECT session_count FROM vyom_rate_limits WHERE user_id=:u AND day=:d"),
        {"u": user_id, "d": today},
    ).first()
    if row and row.session_count > settings.MAX_SESSIONS_PER_DAY:
        raise HTTPException(
            429,
            f"Daily limit of {settings.MAX_SESSIONS_PER_DAY} interviews reached. Come back tomorrow.",
            headers={"Retry-After": "86400"},
        )


def _check_alumni_rate_limit(db: Session, user_id: str) -> None:
    today = date.today()
    row = db.execute(
        text("""
            SELECT COUNT(*) AS cnt FROM vyom_alumni_questions
            WHERE submitted_by = :u AND DATE(created_at) = :d
        """),
        {"u": user_id, "d": today},
    ).first()
    if row and row.cnt >= settings.MAX_ALUMNI_PER_DAY:
        raise HTTPException(
            429,
            f"Daily limit of {settings.MAX_ALUMNI_PER_DAY} alumni submissions reached.",
            headers={"Retry-After": "86400"},
        )


def _load_session(db: Session, session_id: str, user_id: str) -> dict:
    row = db.execute(
        text("SELECT * FROM vyom_sessions WHERE id=:id AND user_id=:u"),
        {"id": session_id, "u": user_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Session not found")
    return dict(row)


def _load_messages(db: Session, session_id: str) -> list[dict]:
    rows = db.execute(
        text("SELECT role, content FROM vyom_messages WHERE session_id=:s ORDER BY id ASC"),
        {"s": session_id},
    ).mappings().all()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _save_message(db: Session, session_id: str, role: str, content: str) -> None:
    db.execute(
        text("INSERT INTO vyom_messages (session_id, role, content) VALUES (:s, :r, :c)"),
        {"s": session_id, "r": role, "c": content},
    )
    db.commit()


def _session_to_cfg(row: dict) -> dict:
    return {
        "name": row.get("name") or "",
        "role": row["role"],
        "level": row["level"],
        "company": row.get("company") or "",
        "duration_min": row["duration_min"],
        "difficulty": row["difficulty"],
        "mode": row["mode"],
        "round": row.get("round") or "full",
        "round_label": row.get("round_label") or "",
        "round_detail": row.get("round_detail") or "",
        "focus": (row["focus"] or "").split(",") if row.get("focus") else [],
        "intro": row.get("intro") or "",
    }


def _update_session_counters(db: Session, session_id: str) -> None:
    db.execute(
        text("""
            UPDATE vyom_sessions s
            LEFT JOIN (
                SELECT session_id,
                       SUM(role = 'user') AS u_cnt,
                       SUM(role = 'assistant') AS a_cnt
                FROM vyom_messages
                WHERE session_id = :s
                GROUP BY session_id
            ) m ON m.session_id = s.id
            SET s.user_message_count = COALESCE(m.u_cnt, 0),
                s.assistant_message_count = COALESCE(m.a_cnt, 0)
            WHERE s.id = :s
        """),
        {"s": session_id},
    )
    db.commit()


def _finalize_session(db: Session, session_id: str, completion_type: str) -> None:
    db.execute(
        text("""
            UPDATE vyom_sessions
            SET status = CASE WHEN status='active' THEN 'completed' ELSE status END,
                ended_at = COALESCE(ended_at, NOW()),
                actual_duration_seconds = COALESCE(
                    actual_duration_seconds,
                    TIMESTAMPDIFF(SECOND, started_at, NOW())
                ),
                completion_type = COALESCE(completion_type, :ct)
            WHERE id = :id
        """),
        {"id": session_id, "ct": completion_type},
    )
    db.commit()
    _update_session_counters(db, session_id)


@app.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)):
    db_status = "ok"
    try:
        db.execute(text("SELECT 1")).first()
    except Exception as e:
        log.error("health DB check failed: %s", e)
        db_status = "down"
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db=db_status,
        model_interview=settings.MODEL_INTERVIEW,
        model_debrief=settings.MODEL_DEBRIEF,
    )


@app.post("/session/start", response_model=StartSessionResponse)
async def start_session(
    body: StartSessionRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    _check_rate_limit(db, user_id)

    ctx = {}
    try:
        ctx = get_student_context(user_id, db)
    except Exception as e:
        log.warning("get_student_context failed for uid=%s: %s", user_id, e)

    if ctx.get("name"):
        body.name = ctx["name"][:120]

    resume_text = ""
    if ctx.get("resume_url"):
        try:
            resume_text = await extract_resume_text(ctx["resume_url"])
        except Exception as e:
            log.warning("extract_resume_text failed: %s", e)

    silent_lines = []

    if ctx.get("enrollments"):
        course_lines = []
        for e in ctx["enrollments"]:
            status = "Certified" if e["certified"] else f"{e['progress']}% complete"
            course_lines.append(f"  - {e['course']} ({status})")
        silent_lines.append("ENROLLED COURSES:\n" + "\n".join(course_lines))

    if ctx.get("education"):
        silent_lines.append(f"EDUCATION: {ctx['education']}")

    status = ctx.get("current_status")
    role_title = ctx.get("current_role")
    employer = ctx.get("employer")

    if status == "working_professional" and (role_title or employer):
        who = f"{role_title} at {employer}" if role_title and employer else (role_title or employer)
        silent_lines.append(
            f"CURRENT STATUS: Working professional — currently {who}. "
            f"They are targeting this new role. Probe their motivation for the change "
            f"and what they're seeking in this opportunity. Ask naturally — do not make it sound interrogative."
        )
    elif status == "working_professional":
        silent_lines.append(
            "CURRENT STATUS: Working professional with experience. "
            "Probe their reason for exploring this role. Treat them as experienced — "
            "raise the bar accordingly."
        )
    elif status == "student_or_fresher":
        silent_lines.append(
            "CURRENT STATUS: Student or fresher — no full-time work experience. "
            "Focus on academic projects, internships, learning experiences. "
            "Do NOT ask 'why are you leaving your current job' or 'current employer'."
        )

    if ctx.get("skills"):
        silent_lines.append(f"STATED SKILLS (test at least 2 of these): {ctx['skills']}")

    if ctx.get("ai_profile"):
        silent_lines.append(
            "AI-GENERATED PROFILE (highest quality data — use for deep personalization):\n"
            + str(ctx["ai_profile"])[:2000]
        )

    if resume_text:
        silent_lines.append("--- RESUME ---\n" + resume_text[:2500])

    if ctx.get("psycho"):
        p = ctx["psycho"]
        top = ", ".join(p["top"]) if p["top"] else p.get("type", "")
        silent_lines.append(
            f"PERSONALITY (psychometric test result): {p.get('type','')} — "
            f"dominant traits: {top}. "
            f"Analytical types → data-heavy questions with numbers. "
            f"Execution types → scenario-based action questions. "
            f"Collaboration/HR types → people-dynamic and stakeholder questions."
        )

    if silent_lines:
        body.intro = (body.intro or "") + "\n\n" + "\n\n".join(silent_lines)

    session_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO vyom_sessions
            (id, user_id, name, role, level, company, duration_min,
             difficulty, mode, round, round_label, round_detail,
             focus, intro, status)
            VALUES
            (:id, :user_id, :name, :role, :level, :company, :duration_min,
             :difficulty, :mode, :round, :round_label, :round_detail,
             :focus, :intro, 'active')
        """),
        {
            "id": session_id,
            "user_id": user_id,
            "name": body.name,
            "role": body.role,
            "level": body.level,
            "company": body.company,
            "duration_min": body.duration_min,
            "difficulty": body.difficulty,
            "mode": body.mode,
            "round": body.round,
            "round_label": body.round_label,
            "round_detail": body.round_detail,
            "focus": ",".join(body.focus),
            "intro": body.intro,
        },
    )
    db.commit()

    alumni_intel = fetch_alumni_intel(db, body.company, body.role)

    cfg = body.model_dump()
    system_prompt = build_system_prompt(cfg, alumni_intel)

    kickoff = (
        f"The session is starting now. In a SHORT spoken greeting (max 4 sentences), "
        f"greet {body.name or 'the candidate'} by first name, confirm the role "
        f"({body.role}) and that you have about {body.duration_min} minutes together, "
        f"give a brief calming cue, and ask the first warm-up rapport question.\n\n"
        f"CRITICAL FORMATTING — apply to EVERY message you send, not just this one:\n"
        f"- Never use markdown headers (no '#', '##', '###' lines).\n"
        f"- Never use horizontal rules (no '---', '***', '___').\n"
        f"- No section titles. No document-style formatting. Speak conversationally, "
        f"as a human interviewer would over a video call.\n"
        f"- Begin your greeting directly with the candidate's name: 'Hi {body.name or 'there'}! ...'"
    )

    greeting = await call_claude(
        system=system_prompt,
        messages=[{"role": "user", "content": kickoff}],
        model=settings.MODEL_INTERVIEW,
        max_tokens=250,
    )

    _save_message(db, session_id, "assistant", greeting)
    _update_session_counters(db, session_id)

    return StartSessionResponse(session_id=session_id, greeting=greeting)


@app.post("/session/turn", response_model=TurnResponse)
async def session_turn(
    body: TurnRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    locked = db.execute(
        text("SELECT id, status FROM vyom_sessions WHERE id=:id AND user_id=:u FOR UPDATE"),
        {"id": body.session_id, "u": user_id},
    ).first()
    if not locked:
        raise HTTPException(404, "Session not found")
    if locked.status != "active":
        raise HTTPException(400, "Session is not active")

    session_row = _load_session(db, body.session_id, user_id)
    _save_message(db, body.session_id, "user", body.message.strip())

    cfg = _session_to_cfg(session_row)
    alumni_intel = fetch_alumni_intel(db, cfg["company"], cfg["role"])
    system_prompt = build_system_prompt(cfg, alumni_intel)
    messages = _load_messages(db, body.session_id)

    reply = await call_claude(
        system=system_prompt,
        messages=messages,
        model=settings.MODEL_INTERVIEW,
        max_tokens=500,
    )

    _save_message(db, body.session_id, "assistant", reply)
    _update_session_counters(db, body.session_id)

    turn_count = sum(1 for m in messages if m["role"] == "user")
    return TurnResponse(reply=reply, turn_count=turn_count)


@app.post("/session/end", response_model=DebriefResponse)
async def end_session(
    body: EndRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    session_row = _load_session(db, body.session_id, user_id)
    cfg = _session_to_cfg(session_row)

    system_prompt = build_system_prompt(cfg, "")
    messages = _load_messages(db, body.session_id)
    messages.append({"role": "user", "content": DEBRIEF_INSTRUCTION})

    raw = await call_claude(
        system=system_prompt,
        messages=messages,
        model=settings.MODEL_DEBRIEF,
        max_tokens=2500,
    )

    cleaned = raw.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        log.error("Debrief model did not return JSON: %s", raw[:500])
        raise HTTPException(502, "Debrief generation failed")

    try:
        debrief = json.loads(cleaned[start: end + 1])
    except json.JSONDecodeError as e:
        log.error("Debrief JSON parse error: %s — raw=%s", e, raw[:500])
        raise HTTPException(502, "Debrief generation failed")

    db.execute(
        text("""
            INSERT INTO vyom_debriefs
            (session_id, overall, sub_scores, strengths, gaps, star, plan,
             next_focus, one_line, raw_json)
            VALUES
            (:session_id, :overall, :sub_scores, :strengths, :gaps, :star,
             :plan, :next_focus, :one_line, :raw_json)
            ON DUPLICATE KEY UPDATE
              overall=VALUES(overall), sub_scores=VALUES(sub_scores),
              strengths=VALUES(strengths), gaps=VALUES(gaps),
              star=VALUES(star), plan=VALUES(plan),
              next_focus=VALUES(next_focus), one_line=VALUES(one_line),
              raw_json=VALUES(raw_json)
        """),
        {
            "session_id": body.session_id,
            "overall": int(debrief.get("overall", 0)),
            "sub_scores": json.dumps(debrief.get("subScores", {})),
            "strengths": json.dumps(debrief.get("strengths", [])),
            "gaps": json.dumps(debrief.get("gaps", [])),
            "star": json.dumps(debrief.get("starBreakdown", [])),
            "plan": json.dumps(debrief.get("plan", [])),
            "next_focus": debrief.get("nextFocus", ""),
            "one_line": debrief.get("oneLine", ""),
            "raw_json": json.dumps(debrief),
        },
    )
    db.commit()

    _finalize_session(db, body.session_id, completion_type="completed")

    return DebriefResponse(
        session_id=body.session_id,
        overall=int(debrief.get("overall", 0)),
        one_line=debrief.get("oneLine", ""),
        sub_scores=debrief.get("subScores", {}),
        strengths=debrief.get("strengths", []),
        gaps=debrief.get("gaps", []),
        star_breakdown=debrief.get("starBreakdown", []),
        interviewer_thoughts=debrief.get("interviewerThoughts", []),
        plan=debrief.get("plan", []),
        next_focus=debrief.get("nextFocus", ""),
    )


@app.post("/session/abandon")
def abandon_session(
    body: EndRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    _load_session(db, body.session_id, user_id)
    _finalize_session(db, body.session_id, completion_type="abandoned")
    return {"status": "abandoned"}


def _row_to_history_item(row: dict) -> HistoryListItem:
    focus_str = row.get("focus") or ""
    return HistoryListItem(
        session_id=row["id"],
        role=row["role"],
        company=row.get("company") or "",
        level=row["level"],
        difficulty=row["difficulty"],
        mode=row["mode"],
        round=row.get("round") or "full",
        round_label=row.get("round_label") or "",
        focus=[f for f in focus_str.split(",") if f] if focus_str else [],
        planned_duration_min=row["duration_min"],
        actual_duration_seconds=row.get("actual_duration_seconds"),
        user_message_count=row.get("user_message_count") or 0,
        assistant_message_count=row.get("assistant_message_count") or 0,
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
        status=row["status"],
        completion_type=row.get("completion_type"),
        overall=row.get("overall"),
        one_line=row.get("one_line"),
    )


@app.get("/user/history", response_model=HistoryListResponse)
def user_history(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = db.execute(
        text("""
            SELECT s.id, s.role, s.company, s.level, s.difficulty, s.mode,
                   s.round, s.round_label, s.focus,
                   s.duration_min, s.actual_duration_seconds,
                   s.user_message_count, s.assistant_message_count,
                   s.started_at, s.ended_at, s.status, s.completion_type,
                   d.overall, d.one_line
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.user_id = :u
            ORDER BY s.started_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"u": user_id, "lim": limit, "off": offset},
    ).mappings().all()

    total_row = db.execute(
        text("SELECT COUNT(*) AS cnt FROM vyom_sessions WHERE user_id = :u"),
        {"u": user_id},
    ).first()
    total = total_row.cnt if total_row else 0

    return HistoryListResponse(
        sessions=[_row_to_history_item(dict(r)) for r in rows],
        total=total,
    )


@app.get("/user/history/{session_id}", response_model=HistoryDetailResponse)
def user_history_detail(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    row = db.execute(
        text("""
            SELECT s.id, s.role, s.company, s.level, s.difficulty, s.mode,
                   s.round, s.round_label, s.focus,
                   s.duration_min, s.actual_duration_seconds,
                   s.user_message_count, s.assistant_message_count,
                   s.started_at, s.ended_at, s.status, s.completion_type,
                   d.overall, d.one_line, d.raw_json
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.id = :id AND s.user_id = :u
        """),
        {"id": session_id, "u": user_id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Session not found")

    row = dict(row)
    messages = _load_messages(db, session_id)

    debrief = None
    if row.get("raw_json"):
        try:
            debrief = json.loads(row["raw_json"]) if isinstance(row["raw_json"], str) else row["raw_json"]
        except Exception:
            debrief = None

    return HistoryDetailResponse(
        session=_row_to_history_item(row),
        messages=messages,
        debrief=debrief,
    )


@app.get("/user/stats")
def user_stats(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    summary = db.execute(
        text("""
            SELECT
              COUNT(*) AS total_sessions,
              SUM(s.status = 'completed') AS completed,
              SUM(s.status = 'active') AS in_progress,
              SUM(s.completion_type = 'abandoned') AS abandoned,
              SUM(COALESCE(s.actual_duration_seconds, 0)) AS total_seconds,
              SUM(s.user_message_count) AS total_answers,
              AVG(d.overall) AS avg_score,
              MAX(d.overall) AS best_score,
              MIN(d.overall) AS worst_score
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.user_id = :u
        """),
        {"u": user_id},
    ).mappings().first()

    by_role = db.execute(
        text("""
            SELECT s.role, COUNT(*) AS n, AVG(d.overall) AS avg_score
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.user_id = :u AND s.status = 'completed'
            GROUP BY s.role
            ORDER BY n DESC
            LIMIT 10
        """),
        {"u": user_id},
    ).mappings().all()

    by_round = db.execute(
        text("""
            SELECT s.round, COUNT(*) AS n, AVG(d.overall) AS avg_score
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.user_id = :u AND s.status = 'completed'
            GROUP BY s.round
        """),
        {"u": user_id},
    ).mappings().all()

    return {
        "summary": dict(summary) if summary else {},
        "by_role": [dict(r) for r in by_role],
        "by_round": [dict(r) for r in by_round],
    }


@app.post("/alumni/submit")
def submit_alumni_question(
    body: AlumniQuestionSubmit,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    _check_alumni_rate_limit(db, user_id)
    db.execute(
        text("""
            INSERT INTO vyom_alumni_questions
            (submitted_by, company, role, city, round_type, question, interview_date)
            VALUES (:u, :company, :role, :city, :round_type, :question, :interview_date)
        """),
        {
            "u": user_id,
            "company": body.company.strip(),
            "role": body.role.strip(),
            "city": body.city.strip(),
            "round_type": body.round_type.strip(),
            "question": body.question.strip(),
            "interview_date": body.interview_date,
        },
    )
    db.commit()
    return {"status": "submitted", "message": "Thanks — we'll verify and credit your account."}


@app.get("/alumni/preview")
def alumni_preview(
    company: str = Query(..., max_length=120),
    role: str = Query(..., max_length=120),
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    row = db.execute(
        text(r"""
            SELECT COUNT(*) AS cnt, MAX(interview_date) AS latest
            FROM vyom_alumni_questions
            WHERE verified = 1
              AND company LIKE :c ESCAPE '\\'
              AND role LIKE :r ESCAPE '\\'
              AND (interview_date IS NULL OR interview_date >= DATE_SUB(CURDATE(), INTERVAL 180 DAY))
        """),
        {"c": like_escape(company), "r": like_escape(role)},
    ).first()
    return {"count": row.cnt or 0, "latest_date": str(row.latest) if row.latest else None}


@app.get("/")
def spa_root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"status": "ok", "note": "Frontend not built. This is the API only."}


@app.get("/{path:path}")
def spa_catch_all(path: str):
    api_prefixes = ("session", "alumni", "user", "health", "assets", "docs", "openapi.json")
    if path.startswith(api_prefixes):
        raise HTTPException(404, "Not found")
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404, "Not found")