import json
import os
import uuid
from datetime import date
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, get_student_context
from .auth import current_user
from .schemas import (
    StartSessionRequest, StartSessionResponse,
    TurnRequest, TurnResponse,
    EndRequest, DebriefResponse,
    AlumniQuestionSubmit, HealthResponse,
)
from .prompts import build_system_prompt, DEBRIEF_INSTRUCTION
from .db import get_db, get_student_context, fetch_alumni_intel
from .claude_client import call_claude, extract_resume_text

app = FastAPI(title="InterviewIQ API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


# ========================================================================
# Helpers
# ========================================================================

def _check_rate_limit(db: Session, user_id: str) -> None:
    today = date.today()
    row = db.execute(
        text("SELECT session_count FROM vyom_rate_limits WHERE user_id=:u AND day=:d"),
        {"u": user_id, "d": today},
    ).first()
    count = row.session_count if row else 0
    if count >= settings.MAX_SESSIONS_PER_DAY:
        raise HTTPException(
            429,
            f"Daily limit of {settings.MAX_SESSIONS_PER_DAY} sessions reached. "
            "Come back tomorrow.",
        )
    if row:
        db.execute(
            text("UPDATE vyom_rate_limits SET session_count=session_count+1 "
                 "WHERE user_id=:u AND day=:d"),
            {"u": user_id, "d": today},
        )
    else:
        db.execute(
            text("INSERT INTO vyom_rate_limits (user_id, day, session_count) "
                 "VALUES (:u, :d, 1)"),
            {"u": user_id, "d": today},
        )
    db.commit()


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
        text("SELECT role, content FROM vyom_messages "
             "WHERE session_id=:s ORDER BY id ASC"),
        {"s": session_id},
    ).mappings().all()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _save_message(db: Session, session_id: str, role: str, content: str) -> None:
    db.execute(
        text("INSERT INTO vyom_messages (session_id, role, content) "
             "VALUES (:s, :r, :c)"),
        {"s": session_id, "r": role, "c": content},
    )
    db.commit()


def _session_to_cfg(row: dict) -> dict:
    return {
        "name": row["name"] or "",
        "role": row["role"],
        "level": row["level"],
        "company": row["company"] or "",
        "duration_min": row["duration_min"],
        "difficulty": row["difficulty"],
        "mode": row["mode"],
        "round": row.get("round") or "full",
        "round_label": row.get("round_label") or "",
        "round_detail": row.get("round_detail") or "",
        "focus": (row["focus"] or "").split(",") if row["focus"] else [],
        "intro": row["intro"] or "",
    }


# ========================================================================
# Endpoints
# ========================================================================

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
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

    # ── Pull student context from LMS (all optional, graceful fallback) ──
    ctx = {}
    try:
        ctx = get_student_context(user_id, db)
    except Exception:
        pass  # never block the interview — proceed without context

    # Override name from DB if available
    if ctx.get("name"):
        body.name = ctx["name"]

    # Parse resume text from Cloudinary
    resume_text = ""
    if ctx.get("resume_url"):
        try:
            resume_text = await extract_resume_text(ctx["resume_url"])
        except Exception:
            pass

    # ── Build silent student context block ───────────────────────────────
    silent_lines = []

    # Enrolled courses
    if ctx.get("enrollments"):
        course_lines = []
        for e in ctx["enrollments"]:
            status = "Certified" if e["certified"] else f"{e['progress']}% complete"
            course_lines.append(f"  - {e['course']} ({status})")
        silent_lines.append("ENROLLED COURSES:\n" + "\n".join(course_lines))

    # Education
    if ctx.get("education"):
        silent_lines.append(f"EDUCATION: {ctx['education']}")

    # Current status — most important for realistic interview behavior
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

    # Skills
    if ctx.get("skills"):
        silent_lines.append(f"STATED SKILLS (test at least 2 of these): {ctx['skills']}")

    # AI Enhancer profile — richest source, use first if available
    if ctx.get("ai_profile"):
        silent_lines.append(
            "AI-GENERATED PROFILE (highest quality data — use for deep personalization):\n"
            + str(ctx["ai_profile"])[:2000]
        )

    # Resume text
    if resume_text:
        silent_lines.append(
            "RESUME TEXT (cross-question on real projects, claims, gaps — "
            "never tell them you read it):\n" + resume_text[:2500]
        )

    # Psychometric personality
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

    # Append silent block to intro — candidate never sees this
    if silent_lines:
        body.intro = (body.intro or "") + "\n\n" + "\n\n".join(silent_lines)

    # ── Save session ──────────────────────────────────────────────────────
    session_id = str(uuid.uuid4())

    db.execute(
        text("""
            INSERT INTO vyom_sessions
            (id, user_id, name, role, level, company, duration_min,
             difficulty, mode, focus, intro, status)
            VALUES
            (:id, :user_id, :name, :role, :level, :company, :duration_min,
             :difficulty, :mode, :focus, :intro, 'active')
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
            "focus": ",".join(body.focus),
            "intro": body.intro,
        },
    )
    db.commit()

    # Alumni intel injection (The Golden Point)
    alumni_intel = fetch_alumni_intel(db, body.company, body.role)

    cfg = body.model_dump()
    system_prompt = build_system_prompt(cfg, alumni_intel)

    kickoff = (
        f"The session is starting now. Greet {body.name or 'the candidate'} by "
        f"first name, confirm the role ({body.role}) and duration "
        f"({body.duration_min} minutes), offer a brief calming cue, and ask the "
        f"first warm-up rapport question."
    )

    greeting = await call_claude(
        system=system_prompt,
        messages=[{"role": "user", "content": kickoff}],
        model=settings.MODEL_INTERVIEW,
        max_tokens=400,
    )

    _save_message(db, session_id, "assistant", greeting)

    return StartSessionResponse(session_id=session_id, greeting=greeting)


@app.post("/session/turn", response_model=TurnResponse)
async def session_turn(
    body: TurnRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    session_row = _load_session(db, body.session_id, user_id)
    if session_row["status"] != "active":
        raise HTTPException(400, "Session is not active")

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
        raise HTTPException(502, "Debrief model did not return JSON")

    try:
        debrief = json.loads(cleaned[start: end + 1])
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"Debrief JSON parse error: {e}")

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
    db.execute(
        text("UPDATE vyom_sessions SET status='completed', ended_at=NOW() WHERE id=:id"),
        {"id": body.session_id},
    )
    db.commit()

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


@app.get("/session/{session_id}")
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    session_row = _load_session(db, session_id, user_id)
    messages = _load_messages(db, session_id)
    debrief = db.execute(
        text("SELECT raw_json FROM vyom_debriefs WHERE session_id=:s"),
        {"s": session_id},
    ).first()
    debrief_data = json.loads(debrief.raw_json) if debrief else None
    return {"session": session_row, "messages": messages, "debrief": debrief_data}


@app.get("/user/history")
def user_history(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    rows = db.execute(
        text("""
            SELECT s.id, s.role, s.company, s.level, s.difficulty,
                   s.started_at, s.status, d.overall, d.one_line
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.user_id = :u
            ORDER BY s.started_at DESC
            LIMIT 20
        """),
        {"u": user_id},
    ).mappings().all()
    return {"sessions": [dict(r) for r in rows]}


@app.post("/alumni/submit")
def submit_alumni_question(
    body: AlumniQuestionSubmit,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
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
    company: str,
    role: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    row = db.execute(
        text("""
            SELECT COUNT(*) AS cnt, MAX(interview_date) AS latest
            FROM vyom_alumni_questions
            WHERE verified = 1
              AND company LIKE :c
              AND role LIKE :r
              AND (interview_date IS NULL OR interview_date >= DATE_SUB(CURDATE(), INTERVAL 180 DAY))
        """),
        {"c": f"%{company}%", "r": f"%{role}%"},
    ).first()
    return {"count": row.cnt or 0, "latest_date": str(row.latest) if row.latest else None}


# ── SPA catch-all (must be last) ────────────────────────────────────────────

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