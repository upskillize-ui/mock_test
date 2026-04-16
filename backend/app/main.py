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
from .db import get_db
from .auth import current_user
from .schemas import (
    StartSessionRequest, StartSessionResponse,
    TurnRequest, TurnResponse,
    EndRequest, DebriefResponse,
    AlumniQuestionSubmit, HealthResponse,
)
from .prompts import build_system_prompt, fetch_alumni_intel, DEBRIEF_INSTRUCTION
from .claude_client import call_claude

app = FastAPI(title="Vyom API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve React static files (built at Docker build time and placed in ./static)
# This lets one HF Space serve both API (/session/*, /alumni/*, /health) and UI (/)
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

    # THE GOLDEN POINT: inject real alumni questions into the prompt
    alumni_intel = fetch_alumni_intel(db, body.company, body.role)

    cfg = body.model_dump()
    system_prompt = build_system_prompt(cfg, alumni_intel)

    kickoff = (
        f"The session is starting now. Greet {body.name or 'the learner'} by "
        f"first name, confirm the role ({body.role}) and duration "
        f"({body.duration_min} minutes), offer the calming cue, and ask the "
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

    # Save user message
    _save_message(db, body.session_id, "user", body.message.strip())

    # Rebuild context: system prompt (with alumni intel) + all messages
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

    # Build debrief using Sonnet (quality matters here)
    alumni_intel = ""  # debrief doesn't need alumni intel — saves tokens
    system_prompt = build_system_prompt(cfg, alumni_intel)
    messages = _load_messages(db, body.session_id)
    messages.append({"role": "user", "content": DEBRIEF_INSTRUCTION})

    raw = await call_claude(
        system=system_prompt,
        messages=messages,
        model=settings.MODEL_DEBRIEF,
        max_tokens=2500,
    )

    # Parse JSON (strip any accidental fences)
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise HTTPException(502, "Debrief model did not return JSON")

    try:
        debrief = json.loads(cleaned[start: end + 1])
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"Debrief JSON parse error: {e}")

    # Persist
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
    """Fetch full session + messages + debrief (for replay or progress view)."""
    session_row = _load_session(db, session_id, user_id)
    messages = _load_messages(db, session_id)
    debrief = db.execute(
        text("SELECT raw_json FROM vyom_debriefs WHERE session_id=:s"),
        {"s": session_id},
    ).first()
    debrief_data = json.loads(debrief.raw_json) if debrief else None
    return {
        "session": session_row,
        "messages": messages,
        "debrief": debrief_data,
    }


@app.get("/user/history")
def user_history(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """List past sessions for progress tracking."""
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


# ------------------------------------------------------------------------
# GOLDEN POINT: Alumni intel contribution endpoint
# ------------------------------------------------------------------------

@app.post("/alumni/submit")
def submit_alumni_question(
    body: AlumniQuestionSubmit,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Placed alumni submit real interview questions they were asked.
    Admin reviews and flips verified=1 → then it starts getting injected
    into Vyom sessions for the same company+role.

    This is the compounding moat that makes Vyom un-copyable.
    """
    db.execute(
        text("""
            INSERT INTO vyom_alumni_questions
            (submitted_by, company, role, city, round_type, question, interview_date)
            VALUES
            (:u, :company, :role, :city, :round_type, :question, :interview_date)
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
    """For the setup screen: show learner how many real alumni questions
    exist for their target company + role, as a trust signal.
    """
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


# ------------------------------------------------------------------------
# Serve React SPA — catch-all for non-API routes
# Must be the LAST route so it doesn't shadow /session/*, /alumni/*, etc.
# ------------------------------------------------------------------------

@app.get("/")
def spa_root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"status": "ok", "note": "Frontend not built. This is the API only."}


@app.get("/{path:path}")
def spa_catch_all(path: str):
    # Don't swallow API paths — they're declared above and take precedence,
    # but be defensive about unmatched paths that start with API prefixes.
    api_prefixes = ("session", "alumni", "user", "health", "assets", "docs", "openapi.json")
    if path.startswith(api_prefixes):
        raise HTTPException(404, "Not found")
    # Serve the SPA shell for any other route
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404, "Not found")
