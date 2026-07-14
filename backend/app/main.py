import asyncio
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Query, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError
from jose import jwt, JWTError

from .config import settings
from .db import get_db, get_student_context, fetch_alumni_intel, like_escape
from .auth import current_user
from . import stages
from . import compliance
from . import tts
from . import stt
from . import delivery
from . import dev_auth
from . import presence
from .schemas import (
    StartSessionRequest, StartSessionResponse,
    TurnRequest, TurnResponse, STTResponse,
    ReaskRequest, ReaskResponse,
    EditLastAnswerRequest, EditLastAnswerResponse,
    FocusEventRequest, FocusEventResponse, WrapRequest, WrapResponse,
    RatingRequest, RatingResponse, SessionState,
    SessionMessagesResponse,
    EndRequest, DebriefResponse,
    AlumniQuestionSubmit, HealthResponse,
    HistoryListResponse, HistoryListItem, HistoryDetailResponse,
    ConsentRequest, ConsentResponse,
    DeleteRequestResponse, DeleteConfirmRequest, DeleteConfirmResponse,
    PurgeResponse,
)
from .prompts import (
    build_system_prompt, DEBRIEF_INSTRUCTION, stage_turn_directive,
    build_kickoff, parse_kickoff, rating_ask, reask_line, REASK_DIRECTIVE, turn_tone,
    mute_fork_line, MUTE_FORK_DIRECTIVE,
)
from .claude_client import call_claude, extract_resume_text


def _as_obj(v, default):
    """Coerce a MySQL JSON column (may arrive as str or already-parsed) to an object."""
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default
    return default

class _PIIRedactionFilter(logging.Filter):
    """INT-07: last-line-of-defence PII scrub applied to every log record.

    The formatted message is passed through compliance.redact() so any email or
    phone-like string that slips into a log line (e.g. echoed in an upstream error
    body) is masked at log-write. Learner message content, names and emails must
    never be logged in the clear.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = compliance.redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
for _h in logging.getLogger().handlers:
    _h.addFilter(_PIIRedactionFilter())
log = logging.getLogger(__name__)


app = FastAPI(title="InterviewIQ API", version="2.1.0")

# Voice config visibility — one line at startup so a misconfigured flag (feature
# built but not enabled, or a voice mismatch) is obvious in ten seconds.
log.info(
    "Voice: TTS=%s STT=%s VOICE=%s model=%s speakers=%s/%s",
    settings.TTS_ENABLED, settings.STT_ENABLED, settings.VOICE_ENABLED,
    settings.TTS_MODEL, settings.TTS_VOICE_FEMALE, settings.TTS_VOICE_MALE,
)

# INT-09: the daily-session cap is the production cost-abuse guard and is NOT removed.
# It is only bypassed in development, so local UAT is never blocked.
if settings.APP_ENV == "development":
    log.warning("dev mode: session cap bypassed")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Strict CSP for the whole app. The frontend and the /dev/login page both load only
# same-origin scripts (script-src 'self'), so this is never weakened for them.
_STRICT_CSP = (
    "default-src 'self'; img-src 'self' data:; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "script-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'"
)
# Swagger UI (/docs) and ReDoc (/redoc) load their bundle + stylesheet (and, for
# ReDoc, a web worker) from the jsDelivr CDN — with the strict CSP those pages render
# blank. Relax ONLY these two paths to allow that one CDN's scripts/styles (plus the
# ReDoc worker + doc favicons). Applied in dev AND prod because API docs are meant to
# load them. Every other route keeps _STRICT_CSP.
_DOCS_PATHS = frozenset({"/docs", "/redoc"})
_DOCS_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https://cdn.jsdelivr.net https://fastapi.tiangolo.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
    "script-src 'self' https://cdn.jsdelivr.net; connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'self'"
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path in _DOCS_PATHS:
        # Force (not setdefault) the docs CSP so the API-docs pages can load jsDelivr.
        response.headers["Content-Security-Policy"] = _DOCS_CSP
    else:
        response.headers.setdefault("Content-Security-Policy", _STRICT_CSP)
    return response


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


def register_dev_login(app_) -> bool:
    """DEV ONLY — mount GET /dev/login when APP_ENV == 'development'.

    Outside development the route is NOT registered at all (so it 404s — see the
    "dev" prefix in the SPA catch-all), and in production it is never created. When
    enabled, opening http://localhost:8000/dev/login in ANY browser mints a 30-day
    dev token, writes it to localStorage for the frontend origin, and redirects there
    already logged in — eliminating the copy-paste / wrong-tab / stale-token failure
    modes entirely. NEVER expose this in production.
    """
    if settings.APP_ENV != "development":
        return False

    log.warning("DEV LOGIN ENABLED — development only: GET /dev/login mints a 30-day token")

    @app_.get("/dev/login")
    def dev_login():
        # Mint a fresh 30-day token and hand it to the FRONTEND origin via a URL
        # fragment (localStorage is per-origin — writing it here on the backend origin
        # would be invisible to the frontend). The frontend's dev receiver stores it.
        redirect = settings.ALLOWED_ORIGINS[0] if settings.ALLOWED_ORIGINS else "http://localhost:5173"
        token, _ = dev_auth.build_dev_token(
            settings.JWT_SECRET, days=30,
            audience=settings.JWT_AUDIENCE, issuer=settings.JWT_ISSUER,
        )
        # no-store so a browser never serves a cached redirect carrying a stale token.
        return RedirectResponse(
            dev_auth.dev_login_redirect_url(redirect, token),
            status_code=302, headers={"Cache-Control": "no-store"},
        )

    return True


register_dev_login(app)


def _check_rate_limit(db: Session, user_id: str) -> None:
    """INT-09 daily-session cap — the production cost-abuse guard.

    Bypassed ENTIRELY in development so local UAT (which burns sessions fast) is never
    blocked: we neither count the session nor enforce the cap. Any other APP_ENV —
    production included — is unchanged and still enforced.
    """
    if settings.APP_ENV == "development":
        return

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
    # INT-07: soft-deleted sessions (deleted_at set) are invisible to the owner.
    row = db.execute(
        text("SELECT * FROM vyom_sessions WHERE id=:id AND user_id=:u AND deleted_at IS NULL"),
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


def _load_debrief_messages(db: Session, session_id: str) -> tuple[list[dict], set[int]]:
    """INT-11: transcript for the debrief with each learner answer prefixed by a
    stable `[answer #<id>]` tag, so the scoring call can echo that answer_id back in
    perAnswerScores and we join on it (instead of a fragile positional zip).

    Returns (messages, valid_answer_ids) where valid_answer_ids is the set of real
    user-message ids — used to reject any answerId the model might hallucinate.
    """
    rows = db.execute(
        text("SELECT id, role, content FROM vyom_messages WHERE session_id=:s ORDER BY id ASC"),
        {"s": session_id},
    ).mappings().all()
    messages: list[dict] = []
    valid_answer_ids: set[int] = set()
    for r in rows:
        content = r["content"]
        if r["role"] == "user":
            valid_answer_ids.add(int(r["id"]))
            content = f"[answer #{r['id']}] {content}"
        messages.append({"role": r["role"], "content": content})
    return messages, valid_answer_ids


def _delivery_profile(db: Session, session_id: str) -> dict:
    """Phase 3 Part D: aggregate the stored per-answer delivery metrics for a
    session into the readout Delivery Profile (or a 'not enough voice data' notice).
    Reads only the additive delivery_metrics column; typed answers have none.

    When the feature is off we skip the query entirely (so the readout never depends
    on migration 004), and any DB error degrades to an empty profile rather than
    breaking the billed debrief."""
    if not settings.DELIVERY_METRICS_ENABLED:
        return _with_tts_cost(delivery.aggregate([]), session_id)
    try:
        rows = db.execute(
            text("SELECT delivery_metrics FROM vyom_messages "
                 "WHERE session_id=:s AND role='user' AND delivery_metrics IS NOT NULL ORDER BY id ASC"),
            {"s": session_id},
        ).mappings().all()
    except Exception as e:
        log.warning("delivery profile query skipped: %s", type(e).__name__)
        return _with_tts_cost(delivery.aggregate([]), session_id)
    spoken = [_as_obj(r["delivery_metrics"], None) for r in rows]
    return _with_tts_cost(
        delivery.aggregate([m for m in spoken if isinstance(m, dict)]), session_id
    )


def _with_tts_cost(profile: dict, session_id: str) -> dict:
    """Attach this session's TTS cost meter to the delivery block.

    INTERNAL, not candidate-facing: the readout never renders it. It rides here because
    the delivery block is the one place we already aggregate per-session voice data, and
    because the E2 sentence-split (2-3x the vendor calls) has to be MEASURED in seconds
    before anyone can argue about it. This is the number that feeds the Sarvam credits
    application and the fallback decision on the 2-call lever.
    """
    if not settings.TTS_ENABLED:
        return profile
    try:
        cost = tts.session_cost(session_id)
    except Exception as e:
        log.warning("tts cost meter unavailable: %s", type(e).__name__)
        return profile
    profile["tts"] = cost
    log.info(
        "tts cost: session=%s billed_seconds=%.1f billed_clips=%d "
        "cached_seconds=%.1f cache_hits=%d unmeasured=%d",
        session_id, cost["vendor_seconds"], cost["vendor_calls"],
        cost["cached_seconds"], cost["cache_hits"], cost["unmeasured_clips"],
    )
    return profile


def _save_message(db: Session, session_id: str, role: str, content: str) -> None:
    db.execute(
        text("INSERT INTO vyom_messages (session_id, role, content) VALUES (:s, :r, :c)"),
        {"s": session_id, "r": role, "c": content},
    )
    db.commit()


def _resolve_speaker(voice: str | None) -> str:
    """Map the learner's voice preference to a Sarvam speaker id (default female)."""
    return settings.TTS_VOICE_MALE if (voice or "").lower() == "male" else settings.TTS_VOICE_FEMALE


async def _try_tts(session_id: str, text_out: str, voice: str | None) -> str | None:
    """Best-effort synth of ONE clip → a relative audio_url, or None. Never raises;
    TTS must never block the interview (question text always goes out anyway).

    This is the SINGLE-LINE path: the re-ask, the mute fork, the confidence-rating ask.
    Interviewer REPLIES do not come through here — they are synthesised sentence by
    sentence by _try_tts_segments below, and synthesising them whole as well was billing
    the same audio twice (see the 2-call lever in FIXUP_SPRINT_REPORT.md).
    """
    if not settings.TTS_ENABLED:
        return None
    try:
        h = await tts.get_audio_hash(session_id, text_out, _resolve_speaker(voice))
        return f"/session/audio/{h}" if h else None
    except Exception as e:
        log.warning("tts synth skipped: %s", type(e).__name__)
        return None


# E2 pacing. A real interviewer breathes between sentences and lets the question land.
INTER_SENTENCE_PAUSE_MS = 380     # spec: 300-450ms between sentences
PRE_QUESTION_PAUSE_MS = 700       # spec: ~700ms before the actual question


async def _try_tts_segments(session_id: str, text_out: str, voice: str | None) -> list[dict]:
    """E2: synthesize ONE CLIP PER SENTENCE.

    Returns [{text, audio_url, pause_before_ms}] so the client can play them in order,
    hold a human beat between them, and advance the caption in exact lockstep with the
    audio (no progress-bar interpolation).

    This is the ONLY synth path for an interviewer reply. It is N vendor CALLS instead of
    1 — but Sarvam bills AUDIO, and the sentences are the same words as the reply, so in
    SECONDS the split is very nearly free. What was not free was the whole-reply clip we
    used to synthesise alongside it and then almost never play (the tts cost meter put
    that at ~50% of the bill), so that call is gone.

    Never blocks the interview: a sentence whose synth fails simply carries a null
    audio_url and the client shows its caption for a beat and moves on.
    """
    if not settings.TTS_ENABLED:
        return []
    sentences = tts.split_sentences(text_out)
    if not sentences:
        return []
    urls = await asyncio.gather(*[_try_tts(session_id, s, voice) for s in sentences])

    segments = []
    last = len(sentences) - 1
    for i, (sentence, url) in enumerate(zip(sentences, urls)):
        if i == 0:
            pause = 0
        elif i == last and last > 0:
            pause = PRE_QUESTION_PAUSE_MS   # let the question land
        else:
            pause = INTER_SENTENCE_PAUSE_MS
        segments.append({"text": sentence, "audio_url": url, "pause_before_ms": pause})
    return segments


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
        # Realism v2: the identity improvised at session start, replayed every turn.
        "interviewer_identity": row.get("interviewer_identity") or "",
        # PART 1: the roster-picked name — the persona IS this person all session.
        "interviewer_name": row.get("interviewer_name") or "",
    }


def _build_state(row: dict, *, stale: bool = False) -> SessionState:
    """INT-04: assemble the client-facing state object from a session row.

    INT-06: status/started_at/stale ride along so the frontend can resume after a
    refresh (only the state endpoint fills them; start/turn/rating leave them None).
    """
    level = row.get("level", "")
    current_stage = row.get("current_stage") or "WARMUP"
    round_index = int(row.get("round_index") or 0)
    awaiting = bool(row.get("awaiting_rating"))
    return SessionState(
        current_stage=current_stage,
        round_index=round_index,
        stage_total=stages.stage_total(level, current_stage),
        awaiting_rating=awaiting,
        last_answer_id=row.get("last_answer_id"),
        answer_count=int(row.get("answer_count") or 0),
        answer_cap=settings.MAX_ANSWERS_PER_SESSION,
        next_action=stages.next_action(current_stage, awaiting),
        stage_label=stages.stage_label(current_stage, round_index, level, awaiting),
        status=row.get("status"),
        started_at=row.get("started_at"),
        stale=stale,
        # Voice Phase 2: spoken input exists only when both flags are on. The
        # frontend gates the mic further (BEHAVIOURAL stage + consent).
        stt_available=bool(settings.STT_ENABLED and settings.VOICE_ENABLED),
        # Interview Room: once wrapped early this is set, and next_action is already
        # "readout" — so a refresh lands on the readout instead of resuming.
        early_wrap_reason=row.get("early_wrap_reason") or None,
    )


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
                current_stage = 'DONE',
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

    # Voice Phase 2 (Decision 1 — consent at point of capture): starting a session
    # never requires voice consent, even when VOICE_ENABLED is true. Typed-only
    # learners must be able to start normally. Voice-recording consent is enforced
    # exactly where audio is captured — the first-mic-use modal (frontend) and the
    # /session/stt consent gate (server-side 403). See VOICE_PHASE2_REPORT.md §6.

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
             focus, intro, status, current_stage)
            VALUES
            (:id, :user_id, :name, :role, :level, :company, :duration_min,
             :difficulty, :mode, :round, :round_label, :round_detail,
             :focus, :intro, 'active', 'WARMUP')
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

    # Realism v2: no fixed greeting. The model improvises a distinct interviewer
    # identity for THIS session and opens in it; we persist the one-line identity so
    # every later turn is prompted to stay in character. Higher temperature-equivalent
    # variety comes from the instruction itself (see prompts.build_kickoff).
    raw_kickoff = await call_claude(
        system=system_prompt,
        messages=[{"role": "user", "content": build_kickoff(cfg)}],
        model=settings.MODEL_INTERVIEW,
        max_tokens=500,
    )
    # PART 1: persist the roster-picked interviewer name so every later turn speaks as
    # that same person. Defensive — a missing column must never break a session start.
    if body.interviewer_name:
        try:
            db.execute(
                text("UPDATE vyom_sessions SET interviewer_name=:n WHERE id=:id"),
                {"n": body.interviewer_name[:40], "id": session_id},
            )
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("interviewer_name not stored (apply migration 006?): %s", type(e).__name__)

    # Interview Room: remember whether they JOINED with the camera on. Defensive — a
    # missing column (migration 006 not applied) must never break starting a session;
    # the room then simply runs without the camera-based ladder.
    if body.camera_at_join:
        try:
            db.execute(
                text("UPDATE vyom_sessions SET camera_at_join=1 WHERE id=:id"),
                {"id": session_id},
            )
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("camera_at_join not stored (apply migration 006?): %s", type(e).__name__)

    identity, greeting = parse_kickoff(raw_kickoff)
    if identity:
        # Persist for cross-turn continuity. Defensive: if migration 005 has not been
        # applied yet the column is missing — that must NOT break starting a session.
        # Without it the interview still runs; it just loses identity continuity.
        try:
            db.execute(
                text("UPDATE vyom_sessions SET interviewer_identity=:i WHERE id=:id"),
                {"i": identity, "id": session_id},
            )
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("interviewer_identity not stored (apply migration 005?): %s",
                        type(e).__name__)
        # Dev-only: surfaces the improvised identity so UAT can confirm three fresh
        # sessions really do produce three different interviewers. Never sent to the
        # candidate; contains no learner PII.
        if settings.APP_ENV != "production":
            log.info("interviewer identity: %s", identity)

    _save_message(db, session_id, "assistant", greeting)
    _update_session_counters(db, session_id)

    audio_segments = await _try_tts_segments(session_id, greeting, body.voice)

    state = _build_state({
        "level": body.level,
        "current_stage": "WARMUP",
        "round_index": 0,
        "awaiting_rating": 0,
        "last_answer_id": None,
        "answer_count": 0,
    })
    return StartSessionResponse(
        session_id=session_id, greeting=greeting, state=state,
        stt_available=bool(settings.STT_ENABLED and settings.VOICE_ENABLED),
        audio_segments=audio_segments,
        # Dev/UAT only — lets the console prove each session invents a new interviewer.
        interviewer_identity=(identity or None) if settings.APP_ENV != "production" else None,
    )


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
    st = session_row.get("current_stage") or "WARMUP"
    level = session_row.get("level", "")
    round_index = int(session_row.get("round_index") or 0)
    awaiting = bool(session_row.get("awaiting_rating"))
    answer_count = int(session_row.get("answer_count") or 0)

    # INT-04 — enforce the stage machine. Out-of-order posts return 409.
    if st in ("READOUT", "DONE", "SETUP"):
        raise HTTPException(409, "This interview has finished — there are no more questions to answer.")
    if awaiting:
        raise HTTPException(409, "Please rate your confidence in your previous answer before continuing.")
    if body.stage and body.stage.strip().upper() != st:
        current_name = stages.STAGE_LABELS.get(st, st.title())
        raise HTTPException(409, f"Out of order: the interview is on the {current_name} round right now.")
    if answer_count >= settings.MAX_ANSWERS_PER_SESSION:
        raise HTTPException(409, "You've reached the maximum number of answers for one session.")

    # E7.7: the per-question clock expired. "skip" means NOTHING was captured — the
    # SERVER writes the marker text (never the client), so the transcript is honest about
    # what happened and cannot be forged. "partial" means we cut them off mid-answer and
    # what we had was submitted; it is scored like any other short answer.
    timed_out = body.timeout or ""
    skipped = timed_out == "skip"
    content = stages.TIMEOUT_SKIP_TEXT if skipped else body.message.strip()

    # Phase 3 Part C: a spoken answer carries delivery metrics echoed from
    # /session/stt. Re-validate the client payload and store it on the answer's row
    # (typed answers stay NULL). Informational only — never affects scoring. A skip has
    # no recording behind it, so it carries no metrics either.
    dm = None
    if settings.DELIVERY_METRICS_ENABLED and not skipped:
        dm = delivery.sanitize(body.delivery_metrics)

    # Persist the answer and capture its id (used later as the rating target). Only a
    # spoken answer with metrics touches the additive delivery_metrics column, so the
    # common path (typed answers / feature off) never depends on migration 004.
    if dm:
        res = db.execute(
            text("INSERT INTO vyom_messages (session_id, role, content, delivery_metrics) "
                 "VALUES (:s, 'user', :c, :dm)"),
            {"s": body.session_id, "c": content, "dm": json.dumps(dm)},
        )
    else:
        res = db.execute(
            text("INSERT INTO vyom_messages (session_id, role, content) VALUES (:s, 'user', :c)"),
            {"s": body.session_id, "c": content},
        )
    db.commit()
    answer_id = int(res.lastrowid)

    # FIX 1/2: only a *substantive* answer earns a confidence rating and spends a
    # planned question slot. A non-answer ("I don't know" / "skip" / a bare
    # clarification request) is caught here by the cheap deterministic guard —
    # before any LLM judgement — so we never show a rating widget for it, and it
    # does not consume one of the round's questions (the interviewer steps down /
    # re-asks on the same topic instead). WARMUP and REVERSE are unaffected: they
    # are never rating-gated, so consumes_question_slot() returns True for them.
    #
    # E7.7: a skip is a non-answer by construction (we never ask them to rate a question
    # they never got to answer), and it spends no slot in any scored round.
    substantive = False if skipped else not stages.is_non_substantive(content)
    round_index_after = (
        round_index + 1
        if stages.consumes_question_slot(st, substantive, timed_out_skip=skipped)
        else round_index
    )

    cfg = _session_to_cfg(session_row)
    alumni_intel = fetch_alumni_intel(db, cfg["company"], cfg["role"])
    system_prompt = build_system_prompt(cfg, alumni_intel)
    messages = _load_messages(db, body.session_id)
    # Interview Room: if attention has drifted (or the camera went off), the interviewer
    # raises it ONCE on this turn, in their own improvised voice. Tone only — the round
    # plan, difficulty and rigor are untouched.
    directive = stage_turn_directive(
        cfg, st, round_index_after, substantive=substantive,
        presence_note=_presence_note(db, session_row),
        # PART 1: what they ACTUALLY just said. No summarisation call — the raw answer
        # (clamped) is the cheapest and most faithful thing to react to. A skip has no
        # answer to react to, so we pass nothing rather than the marker: "react to
        # something specific in it" must not be aimed at our own placeholder.
        prior_answer_summary="" if skipped else content[:600],
        timeout=timed_out,
    )

    reply = await call_claude(
        system=system_prompt,
        messages=messages,
        model=settings.MODEL_INTERVIEW,
        max_tokens=500,
        system_suffix=directive,
    )
    _save_message(db, body.session_id, "assistant", reply)

    # Advance the stage machine.
    if st == "REVERSE":
        # Not rating-gated; advance straight to READOUT when the round completes.
        new_stage, new_round = stages.advance_after_reverse(round_index_after, level)
        new_awaiting, new_last = 0, None
    elif stages.should_await_rating(st, substantive):
        # DOMAIN/BEHAVIOURAL/CASE substantive answer: hold here until the learner
        # submits a confidence rating (INT-01); advancement happens in /turn/rating.
        new_stage, new_round = st, round_index_after
        new_awaiting, new_last = 1, answer_id
    elif stages.is_rating_gated(st):
        # Rating-gated stage but a non-substantive answer (FIX 1): no rating widget,
        # and the slot was not consumed (round_index_after == round_index), so the
        # interviewer re-asks / steps down on the same topic. Stay in the stage.
        new_stage, new_round = st, round_index_after
        new_awaiting, new_last = 0, None
    else:
        # WARMUP: not rating-gated (product) — advance straight to the next question.
        new_stage, new_round = stages.advance_after_rating(st, round_index_after, level)
        new_awaiting, new_last = 0, None

    db.execute(
        text("""
            UPDATE vyom_sessions
            SET current_stage=:cs, round_index=:ri, awaiting_rating=:aw,
                last_answer_id=:la, answer_count=answer_count + 1
            WHERE id=:id
        """),
        {"cs": new_stage, "ri": new_round, "aw": new_awaiting,
         "la": new_last, "id": body.session_id},
    )
    db.commit()
    _update_session_counters(db, body.session_id)

    audio_segments = await _try_tts_segments(body.session_id, reply, body.voice)

    # Realism v2: when this answer is rating-gated, IQ asks for the confidence rating
    # ALOUD, so the voice stage can stay hands-free. Text + audio ride on the turn
    # response; the pills remain the fallback (parse-fail / silence) on the client.
    rating_prompt = rating_audio_url = None
    if new_awaiting:
        rating_prompt = rating_ask(answer_id)
        rating_audio_url = await _try_tts(body.session_id, rating_prompt, body.voice)

    state = _build_state({
        "level": level,
        "current_stage": new_stage,
        "round_index": new_round,
        "awaiting_rating": new_awaiting,
        "last_answer_id": new_last,
        "answer_count": answer_count + 1,
    })
    # POSES: the register for this turn. The face follows the words.
    esc = _escalation_level(db, session_row)
    tone = turn_tone(cfg.get("difficulty"), new_stage, esc)

    return TurnResponse(reply=reply, answer_id=answer_id, state=state,
                        audio_segments=audio_segments, tone=tone, escalation_level=esc,
                        rating_prompt=rating_prompt, rating_audio_url=rating_audio_url)


def _focus_counts(db: Session, session_id: str) -> dict:
    """{event_type: count} for this session. Counts only — never media."""
    rows = db.execute(
        text("SELECT event_type, COUNT(*) AS n FROM vyom_focus_events "
             "WHERE session_id=:s GROUP BY event_type"),
        {"s": session_id},
    ).mappings().all()
    return {r["event_type"]: int(r["n"]) for r in rows}


def _escalation_level(db: Session, session_row: dict) -> int:
    """Current focus-ladder level. Defensive: no migration 006 -> no ladder -> 0."""
    try:
        counts = _focus_counts(db, session_row["id"])
    except Exception:
        return 0
    camera_at_join = bool(session_row.get("camera_at_join"))
    total = sum(
        n for t, n in counts.items() if t in presence.ATTENTION_SIGNALS
        and (camera_at_join or t not in presence.CAMERA_SIGNALS)
    )
    return presence.escalation_level(total)


def _presence_note(db: Session, session_row: dict) -> str:
    """The attention/camera line the interviewer should raise on the NEXT turn, in
    persona. Returns "" when there is nothing to say — silence is the default."""
    try:
        counts = _focus_counts(db, session_row["id"])
    except Exception as e:
        # Migration 006 not applied yet -> the room simply has no ladder. Never break a turn.
        log.warning("focus counts unavailable (apply migration 006?): %s", type(e).__name__)
        return ""
    camera_at_join = bool(session_row.get("camera_at_join"))

    # Camera policy first — it is the more consequential ladder.
    cam_action = presence.camera_ladder_action(counts.get("camera_off", 0), camera_at_join)
    cam_note = presence.camera_directive(cam_action)
    if cam_note:
        return cam_note

    attention_total = sum(
        n for t, n in counts.items() if t in presence.ATTENTION_SIGNALS
        and (camera_at_join or t not in presence.CAMERA_SIGNALS)
    )
    return presence.escalation_directive(presence.escalation_level(attention_total))


@app.post("/session/focus-event", response_model=FocusEventResponse)
def session_focus_event(
    body: FocusEventRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Interview Room (Phase C/E): record ONE on-device attention/device signal.

    PRIVACY: this endpoint accepts a string and nothing else. No frame, no image, no
    landmark can reach it — the camera never leaves the browser. The schema is the
    enforcement point, not a comment.

    The server is the authority on the ladder: it re-applies the debounce (a buggy or
    hostile client cannot spam it) and ignores camera signals entirely when the learner
    joined camera-off.
    """
    session_row = _load_session(db, body.session_id, user_id)
    camera_at_join = bool(session_row.get("camera_at_join"))

    if not presence.accepts_event(body.type, camera_at_join):
        # Unknown signal, or a camera signal from a camera-off join -> silently ignored.
        return FocusEventResponse(recorded=False)

    # Server-side debounce: one event per signal per DEBOUNCE_SECONDS.
    last = db.execute(
        text("SELECT TIMESTAMPDIFF(SECOND, MAX(created_at), NOW()) AS since "
             "FROM vyom_focus_events WHERE session_id=:s AND event_type=:t"),
        {"s": body.session_id, "t": body.type},
    ).mappings().first()
    if last and presence.within_debounce(last["since"]):
        counts = _focus_counts(db, body.session_id)
        attention = sum(n for t, n in counts.items() if t in presence.ATTENTION_SIGNALS)
        return FocusEventResponse(
            recorded=False,
            attention_events=attention,
            escalation_level=presence.escalation_level(attention),
            device_action=presence.camera_ladder_action(counts.get("camera_off", 0), camera_at_join),
        )

    db.execute(
        text("INSERT INTO vyom_focus_events (session_id, event_type) VALUES (:s, :t)"),
        {"s": body.session_id, "t": body.type},
    )
    db.commit()

    counts = _focus_counts(db, body.session_id)
    attention = sum(n for t, n in counts.items() if t in presence.ATTENTION_SIGNALS)
    return FocusEventResponse(
        recorded=True,
        attention_events=attention,
        escalation_level=presence.escalation_level(attention),
        device_action=presence.camera_ladder_action(counts.get("camera_off", 0), camera_at_join),
    )


@app.post("/session/wrap", response_model=WrapResponse)
def session_wrap(
    body: WrapRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Interview Room (Phase E): END the interview early, server-side and persisted.

    Refreshing cannot dodge this: the stage is moved to READOUT and the reason stored.
    Scoring is untouched — the debrief runs over the rounds actually completed. We score
    what happened and mark what didn't. Nothing is zeroed as a punishment.
    """
    session_row = _load_session(db, body.session_id, user_id)
    if (session_row.get("status") or "") != "active":
        return WrapResponse(wrapped=False, reason=session_row.get("early_wrap_reason"))

    current_stage = session_row.get("current_stage") or ""
    new_stage, wrapped_at = stages.early_wrap_transition(current_stage)
    reason = (body.reason or "")[:40]

    db.execute(
        text("UPDATE vyom_sessions SET current_stage=:cs, awaiting_rating=0, "
             "last_answer_id=NULL, early_wrap_reason=:r, early_wrap_stage=:st WHERE id=:id"),
        {"cs": new_stage, "r": reason, "st": wrapped_at, "id": body.session_id},
    )
    db.commit()
    log.info("session wrapped early: reason=%s at_stage=%s", reason, wrapped_at)

    row = _load_session(db, body.session_id, user_id)
    return WrapResponse(wrapped=True, reason=reason, state=_build_state(row))


@app.post("/session/reask", response_model=ReaskResponse)
async def session_reask(
    body: ReaskRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """A short spoken nudge, in character, that costs the candidate nothing.

    kind="reask" — the transcription failed: IQ says it didn't catch that and the mic
                   reopens.
    kind="mute"  — the mic is MUTED and an answer is due: IQ offers the fork (unmute, or
                   type). We NEVER auto-unmute — that is always the candidate's act.

    Deliberately side-effect-free on the interview: NO message is inserted, NO stage /
    round_index / answer_count changes. A failed transcription must never cost the
    learner one of the round's question slots.
    """
    session_row = _load_session(db, body.session_id, user_id)
    if (session_row.get("status") or "") != "active":
        raise HTTPException(400, "Session is not active")

    cfg = _session_to_cfg(session_row)
    seed = int(session_row.get("answer_count") or 0)
    is_mute = body.kind == "mute"
    directive = MUTE_FORK_DIRECTIVE if is_mute else REASK_DIRECTIVE
    line = ""
    try:
        # One short in-character line (the system prompt carries the improvised identity).
        line = (await call_claude(
            system=build_system_prompt(cfg, ""),
            messages=[{"role": "user", "content": directive}],
            model=settings.MODEL_INTERVIEW,
            max_tokens=60,
        )).strip()
    except HTTPException:
        line = ""   # upstream model failed — fall back, never block the candidate
    if not line:
        line = mute_fork_line(seed) if is_mute else reask_line(seed)

    audio_url = await _try_tts(body.session_id, line, body.voice)
    return ReaskResponse(reply=line, audio_url=audio_url)


@app.patch("/session/turn/last", response_model=EditLastAnswerResponse)
def edit_last_answer(
    body: EditLastAnswerRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Correct a mis-transcribed answer from the transcript drawer.

    Rewrites the CONTENT of the learner's most recent answer in place, so the debrief
    scores what they meant rather than what STT heard. Idempotent — re-sending the same
    text changes nothing. NO schema change (it updates vyom_messages.content).

    Deliberate limitation: it does NOT re-run the interviewer's reply. IQ has already
    responded to the original wording; regenerating the turn would rewrite history and
    re-bill the model. The corrected text is what gets scored. Flagged in the report.
    """
    if not settings.EDIT_LAST_ANSWER_ENABLED:
        raise HTTPException(404, "Not found")

    session_row = _load_session(db, body.session_id, user_id)
    if (session_row.get("status") or "") != "active":
        raise HTTPException(400, "Session is not active")

    row = db.execute(
        text("SELECT id FROM vyom_messages WHERE session_id=:s AND role='user' "
             "ORDER BY id DESC LIMIT 1"),
        {"s": body.session_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "No answer to edit yet")

    db.execute(
        text("UPDATE vyom_messages SET content=:c WHERE id=:id"),
        {"c": body.message.strip(), "id": int(row["id"])},
    )
    db.commit()
    return EditLastAnswerResponse(updated=True, answer_id=int(row["id"]))


@app.get("/session/{session_id}/state", response_model=SessionState)
def session_state(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    # INT-06: auth-guarded (_load_session filters by user_id) — a second browser on
    # another account cannot fetch this session; it 404s.
    row = _load_session(db, session_id, user_id)

    # Staleness uses the DB clock for both sides to avoid app/DB timezone drift.
    stale = False
    if row.get("status") == "active":
        ts = db.execute(
            text("SELECT MAX(created_at) AS last_at, NOW() AS db_now "
                 "FROM vyom_messages WHERE session_id=:s"),
            {"s": session_id},
        ).mappings().first()
        stale = compliance.is_stale(
            ts["last_at"] if ts else None,
            ts["db_now"] if ts else None,
            settings.SESSION_IDLE_MINUTES,
        )
    return _build_state(row, stale=stale)


@app.get("/session/{session_id}/messages", response_model=SessionMessagesResponse)
def session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """INT-06: full message history for resume after a page refresh.

    Auth-guarded — _load_session enforces the session belongs to the requester.
    """
    _load_session(db, session_id, user_id)
    return SessionMessagesResponse(
        session_id=session_id,
        messages=_load_messages(db, session_id),
    )


@app.get("/session/audio/{audio_hash}")
def session_audio(
    audio_hash: str,
    user_id: str = Depends(current_user),
):
    """Voice Phase 1: serve cached TTS audio by content hash. Auth required.

    The hash is content-addressed (sha256 of preprocessed text + speaker), not
    enumerable; we validate the shape to block any path traversal, then stream the
    cached mp3. Cache is shared across sessions/users by design (questions repeat).
    """
    if not re.fullmatch(r"[0-9a-f]{64}", audio_hash):
        raise HTTPException(404, "Not found")
    path = tts.cache_path(audio_hash)
    if not path.exists():
        raise HTTPException(404, "Audio not available")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


def _has_voice_consent(db: Session, user_id: str) -> bool:
    """True if the user has a voice_recording consent row (INT-07 consent ledger).

    Same query shape as the start_session voice gate — reused, not rebuilt.
    """
    return db.execute(
        text("""
            SELECT 1 FROM vyom_consents
            WHERE user_id = :u AND consent_type = 'voice_recording'
            LIMIT 1
        """),
        {"u": user_id},
    ).first() is not None


@app.post("/session/stt", response_model=STTResponse)
async def session_stt(
    session_id: str = Form(...),
    audio: UploadFile = File(...),
    duration_seconds: float = Form(0.0),
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Voice Phase 3: transcribe a spoken answer to text (ALL answering rounds).

    This does NOT submit the turn — it returns { transcript } for the learner to
    review/edit before pressing Send. Raw audio is transcribed in-memory and
    discarded immediately; it never touches disk or DB (DPDPA: text-only surface).

    Gates (all must pass): STT_ENABLED + VOICE_ENABLED flags, session ownership,
    a voice_recording consent row, and the 10 MB / per-session cost caps. Phase 3
    Part B drops the BEHAVIOURAL-only restriction — voice input is available in every
    answering round (Warm-up, Domain, Behavioural, Case, Reverse). On any
    transcription failure we return {transcript: null} so the learner simply types.
    """
    # Feature + consent-machinery gates. 404 (not 403) when the feature is off so we
    # don't advertise a disabled endpoint.
    if not (settings.STT_ENABLED and settings.VOICE_ENABLED):
        raise HTTPException(404, "Not found")

    session_row = _load_session(db, session_id, user_id)

    # Phase 3 Part B: no stage restriction — the mic works in every answering round.
    if not compliance.consent_gate_ok(settings.VOICE_ENABLED, _has_voice_consent(db, user_id)):
        raise HTTPException(403, "Voice consent is required before using voice input.")

    # Cost guard: cap vendor calls per session (Phase 3: answer cap + 5, mirroring TTS).
    cap = settings.MAX_ANSWERS_PER_SESSION + 5
    if stt.stt_cap_reached(session_id, cap):
        log.info("STT cap reached for session; asking learner to type")
        raise HTTPException(429, "Voice input limit reached for this session — please type your answer.")

    # Read at most cap+1 bytes so an oversized upload is rejected without ever
    # buffering the whole thing. read(n) returns <= n bytes (all of a small file).
    limit = settings.STT_MAX_UPLOAD_BYTES
    audio_bytes = await audio.read(limit + 1)
    if len(audio_bytes) > limit:
        raise HTTPException(413, "Recording is too large. Please keep answers under a few minutes.")
    if not audio_bytes:
        return STTResponse(transcript=None)

    # Count the vendor attempt against the cap, then transcribe. Audio is not
    # retained beyond this call.
    stt.note_stt_call(session_id)
    result = await stt.transcribe_full(
        audio_bytes, audio.content_type, want_timestamps=settings.STT_WITH_TIMESTAMPS
    )
    if result is None:
        return STTResponse(transcript=None, delivery_metrics=None)

    transcript = result.get("transcript")

    # Phase 3 Part C: compute-and-discard delivery metrics from the transcript +
    # recording duration (+ vendor timestamps/confidence if present). The audio is
    # already gone; only these derived numbers survive. Never blocks the turn — any
    # failure just yields null metrics and the learner proceeds normally.
    metrics = None
    if settings.DELIVERY_METRICS_ENABLED and transcript:
        try:
            metrics = delivery.compute(
                transcript, duration_seconds, result.get("timestamps"), result.get("confidence")
            )
        except Exception as e:
            log.warning("delivery metrics compute failed: %s", type(e).__name__)
            metrics = None
    return STTResponse(transcript=transcript, delivery_metrics=metrics)


@app.post("/session/turn/rating", response_model=RatingResponse)
def submit_rating(
    body: RatingRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    locked = db.execute(
        text("""
            SELECT id, status, level, current_stage, round_index,
                   awaiting_rating, last_answer_id, answer_count
            FROM vyom_sessions WHERE id=:id AND user_id=:u FOR UPDATE
        """),
        {"id": body.session_id, "u": user_id},
    ).mappings().first()
    if not locked:
        raise HTTPException(404, "Session not found")

    if not locked["awaiting_rating"]:
        raise HTTPException(409, "No answer is awaiting a confidence rating right now.")
    if body.answer_id != locked["last_answer_id"]:
        raise HTTPException(409, "That answer is not the one awaiting a rating.")

    # PK on answer_id is the hard double-submit guard.
    try:
        db.execute(
            text("""
                INSERT INTO vyom_answer_ratings (answer_id, session_id, rating, stage)
                VALUES (:aid, :sid, :rating, :stage)
            """),
            {"aid": body.answer_id, "sid": body.session_id,
             "rating": body.rating, "stage": locked["current_stage"]},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You've already rated this answer.")

    level = locked["level"] or ""
    new_stage, new_round = stages.advance_after_rating(
        locked["current_stage"], int(locked["round_index"] or 0), level
    )
    db.execute(
        text("""
            UPDATE vyom_sessions
            SET current_stage=:cs, round_index=:ri, awaiting_rating=0, last_answer_id=NULL
            WHERE id=:id
        """),
        {"cs": new_stage, "ri": new_round, "id": body.session_id},
    )
    db.commit()

    state = _build_state({
        "level": level,
        "current_stage": new_stage,
        "round_index": new_round,
        "awaiting_rating": 0,
        "last_answer_id": None,
        "answer_count": int(locked["answer_count"] or 0),
    })
    return RatingResponse(accepted=True, state=state)


@app.post("/session/end", response_model=DebriefResponse)
async def end_session(
    body: EndRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    session_row = _load_session(db, body.session_id, user_id)
    cfg = _session_to_cfg(session_row)

    # Phase 3 Part D: the Delivery Profile is recomputed from stored per-answer
    # metrics on every /session/end (cheap; independent of the billed debrief).
    delivery_profile = _delivery_profile(db, body.session_id)

    # Interview Room: Professional presence — counts + ONE coaching line. Camera-based
    # lines are omitted entirely for a camera-off join (never measured, never reported,
    # never scored). Defensive: no migration 006 -> the card is simply absent.
    try:
        presence_block = presence.presence_readout(
            _focus_counts(db, body.session_id), bool(session_row.get("camera_at_join"))
        )
    except Exception as e:
        log.warning("presence readout skipped (apply migration 006?): %s", type(e).__name__)
        presence_block = {}
    early_wrap = session_row.get("early_wrap_reason") or None

    # Idempotency + cost guard: if a debrief already exists, return it instead of
    # re-running the (billed) Sonnet debrief on every /session/end call.
    existing = db.execute(
        text("SELECT raw_json, overall, overall_band, round_bands, calibration "
             "FROM vyom_debriefs WHERE session_id=:s"),
        {"s": body.session_id},
    ).mappings().first()
    if existing and existing.get("raw_json"):
        d = _as_obj(existing["raw_json"], None)
        if isinstance(d, dict):
            return DebriefResponse(
                session_id=body.session_id,
                overall_band=existing.get("overall_band") or stages.band_for(d.get("overall")),
                round_bands=_as_obj(existing.get("round_bands"), {}),
                one_line=d.get("oneLine", ""),
                sub_scores=d.get("subScores", {}),
                strengths=d.get("strengths", []),
                gaps=d.get("gaps", []),
                star_breakdown=d.get("starBreakdown", []),
                interviewer_thoughts=d.get("interviewerThoughts", []),
                plan=d.get("plan", []),
                next_focus=d.get("nextFocus", ""),
                calibration=_as_obj(existing.get("calibration"), {}),
                delivery=delivery_profile,
                professional_presence=presence_block,
                early_wrap=early_wrap,
            )

    system_prompt = build_system_prompt(cfg, "")
    # INT-11: tag each answer with its answer_id so perAnswerScores can echo it.
    messages, valid_answer_ids = _load_debrief_messages(db, body.session_id)
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
        # INT-07: never log raw model output — it quotes learner answers.
        log.error("Debrief model did not return JSON (len=%d)", len(raw))
        raise HTTPException(502, "Debrief generation failed")

    try:
        debrief = json.loads(cleaned[start: end + 1])
    except json.JSONDecodeError as e:
        log.error("Debrief JSON parse error: %s (len=%d)", e, len(raw))
        raise HTTPException(502, "Debrief generation failed")

    # INT-11: the model's per-answer scores now echo answerId — the join key for
    # both calibration and band math.
    per_scores = debrief.get("perAnswerScores", []) or []
    sub_stages = stages.substantive_stages(per_scores, valid_answer_ids)

    # INT-03: derive readiness bands from the raw (internal) percentages. INT-11:
    # zero any scored round the join says had no substantive answer, so a round of
    # pure "don't know"s can never surface a positive band.
    overall_pct = int(debrief.get("overall", 0))
    overall_band = stages.band_for(overall_pct)
    round_bands = stages.round_bands_from_scores(
        stages.gate_round_scores(debrief.get("roundScores", {}) or {}, sub_stages)
    )

    # INT-02 + INT-11: calibrate learner confidence ratings against the model's
    # per-answer quality scores, JOINED BY answer_id (not positional zip). A rating
    # exists only for a substantive DOMAIN/BEHAVIOURAL/CASE answer; we look up that
    # answer's score by its id, so dropping a mid-list non-answer never misaligns the
    # surviving pairs.
    rating_rows = db.execute(
        text("SELECT answer_id, rating FROM vyom_answer_ratings WHERE session_id=:s ORDER BY answer_id ASC"),
        {"s": body.session_id},
    ).mappings().all()
    ratings = [(int(r["answer_id"]), r["rating"]) for r in rating_rows]
    pairs = stages.calibration_pairs(ratings, per_scores, valid_answer_ids)
    if ratings and not pairs:
        # Ratings exist but nothing joined — the scoring call didn't echo usable
        # answer_ids. Log (no content) so a prompt/model regression is visible; the
        # profile degrades to insufficient_data rather than mispairing.
        log.warning("calibration: %d ratings but 0 joined perAnswerScores by answer_id", len(ratings))
    calibration = stages.calibration_profile(pairs)

    db.execute(
        text("""
            INSERT INTO vyom_debriefs
            (session_id, overall, overall_band, round_bands, calibration,
             sub_scores, strengths, gaps, star, plan, next_focus, one_line, raw_json)
            VALUES
            (:session_id, :overall, :overall_band, :round_bands, :calibration,
             :sub_scores, :strengths, :gaps, :star, :plan, :next_focus, :one_line, :raw_json)
            ON DUPLICATE KEY UPDATE
              overall=VALUES(overall), overall_band=VALUES(overall_band),
              round_bands=VALUES(round_bands), calibration=VALUES(calibration),
              sub_scores=VALUES(sub_scores), strengths=VALUES(strengths),
              gaps=VALUES(gaps), star=VALUES(star), plan=VALUES(plan),
              next_focus=VALUES(next_focus), one_line=VALUES(one_line),
              raw_json=VALUES(raw_json)
        """),
        {
            "session_id": body.session_id,
            "overall": overall_pct,
            "overall_band": overall_band,
            "round_bands": json.dumps(round_bands),
            "calibration": json.dumps(calibration),
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
        overall_band=overall_band,
        round_bands=round_bands,
        one_line=debrief.get("oneLine", ""),
        sub_scores=debrief.get("subScores", {}),
        strengths=debrief.get("strengths", []),
        gaps=debrief.get("gaps", []),
        star_breakdown=debrief.get("starBreakdown", []),
        interviewer_thoughts=debrief.get("interviewerThoughts", []),
        plan=debrief.get("plan", []),
        next_focus=debrief.get("nextFocus", ""),
        calibration=calibration,
        delivery=delivery_profile,
        professional_presence=presence_block,
        early_wrap=early_wrap,
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
            WHERE s.user_id = :u AND s.deleted_at IS NULL
            ORDER BY s.started_at DESC
            LIMIT :lim OFFSET :off
        """),
        {"u": user_id, "lim": limit, "off": offset},
    ).mappings().all()

    total_row = db.execute(
        text("SELECT COUNT(*) AS cnt FROM vyom_sessions WHERE user_id = :u AND deleted_at IS NULL"),
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
            WHERE s.id = :id AND s.user_id = :u AND s.deleted_at IS NULL
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
            WHERE s.user_id = :u AND s.deleted_at IS NULL
        """),
        {"u": user_id},
    ).mappings().first()

    by_role = db.execute(
        text("""
            SELECT s.role, COUNT(*) AS n, AVG(d.overall) AS avg_score
            FROM vyom_sessions s
            LEFT JOIN vyom_debriefs d ON d.session_id = s.id
            WHERE s.user_id = :u AND s.status = 'completed' AND s.deleted_at IS NULL
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
            WHERE s.user_id = :u AND s.status = 'completed' AND s.deleted_at IS NULL
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


# ── INT-07: DPDPA consent + data rights ─────────────────────────────────────

@app.post("/consent", response_model=ConsentResponse)
def record_consent(
    body: ConsentRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Record a consent grant. copy_version pins exactly which wording the learner
    agreed to (legal copy is finalised outside this sprint — see the report)."""
    db.execute(
        text("""
            INSERT INTO vyom_consents (user_id, session_id, consent_type, copy_version)
            VALUES (:u, :sid, :ct, :cv)
        """),
        {"u": user_id, "sid": body.session_id,
         "ct": body.consent_type.strip(), "cv": body.copy_version.strip()},
    )
    db.commit()
    return ConsentResponse(
        accepted=True,
        consent_type=body.consent_type.strip(),
        copy_version=body.copy_version.strip(),
    )


@app.get("/me/data")
def export_my_data(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """DPDPA data-portability: every artefact held for the requester, as JSON.

    Soft-deleted sessions are excluded — once a learner deletes their data the app
    consistently reports it as no longer accessible (the grace window is only for
    internal recovery, not continued access).
    """
    sessions = db.execute(
        text("SELECT * FROM vyom_sessions WHERE user_id = :u AND deleted_at IS NULL "
             "ORDER BY started_at DESC"),
        {"u": user_id},
    ).mappings().all()
    session_ids = [s["id"] for s in sessions]

    messages, ratings, debriefs = [], [], []
    if session_ids:
        messages = db.execute(
            text("SELECT id, session_id, role, content, delivery_metrics, created_at "
                 "FROM vyom_messages WHERE session_id IN :ids ORDER BY id ASC"),
            {"ids": tuple(session_ids)},
        ).mappings().all()
        ratings = db.execute(
            text("SELECT answer_id, session_id, rating, stage, created_at "
                 "FROM vyom_answer_ratings WHERE session_id IN :ids ORDER BY answer_id ASC"),
            {"ids": tuple(session_ids)},
        ).mappings().all()
        debriefs = db.execute(
            text("SELECT * FROM vyom_debriefs WHERE session_id IN :ids"),
            {"ids": tuple(session_ids)},
        ).mappings().all()

    consents = db.execute(
        text("SELECT * FROM vyom_consents WHERE user_id = :u ORDER BY granted_at ASC"),
        {"u": user_id},
    ).mappings().all()

    def _rows(rows):
        return [{k: (v.isoformat() if isinstance(v, (datetime, date)) else v)
                 for k, v in dict(r).items()} for r in rows]

    return {
        "user_id": user_id,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "sessions": _rows(sessions),
        "messages": _rows(messages),
        "ratings": _rows(ratings),
        "debriefs": _rows(debriefs),
        "consents": _rows(consents),
    }


def _delete_token(user_id: str) -> str:
    exp = datetime.utcnow() + timedelta(seconds=settings.DELETE_TOKEN_TTL_SECONDS)
    return jwt.encode(
        {"sub": str(user_id), "purpose": "delete_my_data", "exp": exp},
        settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM,
    )


@app.post("/me/data/delete-request", response_model=DeleteRequestResponse)
def request_data_deletion(user_id: str = Depends(current_user)):
    """Step 1 of erasure: issue a short-lived signed token. Nothing is deleted yet."""
    return DeleteRequestResponse(
        confirmation_token=_delete_token(user_id),
        expires_in_seconds=settings.DELETE_TOKEN_TTL_SECONDS,
        message="Confirm within the time window to delete all your data.",
    )


@app.delete("/me/data", response_model=DeleteConfirmResponse)
def confirm_data_deletion(
    body: DeleteConfirmRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user),
):
    """Step 2 of erasure: verify the token, then soft-delete immediately.

    Soft-delete (deleted_at set) hides all data from the user right away; the
    nightly purge hard-deletes after DELETE_GRACE_DAYS.
    """
    try:
        claims = jwt.decode(
            body.confirmation_token, settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp"], "verify_exp": True},
        )
    except JWTError:
        raise HTTPException(400, "Invalid or expired confirmation token. Please request deletion again.")

    if claims.get("purpose") != "delete_my_data" or str(claims.get("sub")) != str(user_id):
        raise HTTPException(400, "Confirmation token does not match your account.")

    db.execute(
        text("UPDATE vyom_sessions SET deleted_at = NOW() "
             "WHERE user_id = :u AND deleted_at IS NULL"),
        {"u": user_id},
    )
    db.commit()
    return DeleteConfirmResponse(
        deleted=True,
        message="Your data has been scheduled for deletion and is no longer accessible.",
    )


@app.post("/admin/purge", response_model=PurgeResponse)
def admin_purge(
    db: Session = Depends(get_db),
    x_admin_token: str | None = Header(default=None),
):
    """Retention enforcement — call from cron (e.g. nightly).

    - Hard-delete messages of finished sessions past TRANSCRIPT_RETENTION_DAYS.
    - Hard-delete debriefs past DEBRIEF_RETENTION_DAYS.
    - Hard-delete soft-deleted accounts past DELETE_GRACE_DAYS (cascades to
      messages/ratings/debriefs via FK ON DELETE CASCADE).
    All windows compared against the DB clock (NOW()). Guarded by ADMIN_TOKEN.
    """
    if not settings.ADMIN_TOKEN or x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(401, "Admin token required")

    # 1) Transcripts of finished, non-soft-deleted sessions past the window.
    msg_res = db.execute(
        text("""
            DELETE m FROM vyom_messages m
            JOIN vyom_sessions s ON s.id = m.session_id
            WHERE s.status IN ('completed', 'abandoned')
              AND s.deleted_at IS NULL
              AND s.ended_at IS NOT NULL
              AND s.ended_at < DATE_SUB(NOW(), INTERVAL :days DAY)
        """),
        {"days": settings.TRANSCRIPT_RETENTION_DAYS},
    )
    # 2) Debriefs past the (longer) debrief window.
    deb_res = db.execute(
        text("""
            DELETE d FROM vyom_debriefs d
            JOIN vyom_sessions s ON s.id = d.session_id
            WHERE s.deleted_at IS NULL
              AND s.ended_at IS NOT NULL
              AND s.ended_at < DATE_SUB(NOW(), INTERVAL :days DAY)
        """),
        {"days": settings.DEBRIEF_RETENTION_DAYS},
    )
    # 3) Right-to-erasure: hard-delete soft-deleted accounts past the grace window.
    #    Consents are user-scoped (no session FK), so purge them explicitly first.
    con_res = db.execute(
        text("""
            DELETE c FROM vyom_consents c
            WHERE c.user_id IN (
                SELECT DISTINCT user_id FROM vyom_sessions
                WHERE deleted_at IS NOT NULL
                  AND deleted_at < DATE_SUB(NOW(), INTERVAL :days DAY)
            )
        """),
        {"days": settings.DELETE_GRACE_DAYS},
    )
    sess_res = db.execute(
        text("""
            DELETE FROM vyom_sessions
            WHERE deleted_at IS NOT NULL
              AND deleted_at < DATE_SUB(NOW(), INTERVAL :days DAY)
        """),
        {"days": settings.DELETE_GRACE_DAYS},
    )
    db.commit()

    return PurgeResponse(
        messages_purged=msg_res.rowcount or 0,
        debriefs_purged=deb_res.rowcount or 0,
        sessions_hard_deleted=sess_res.rowcount or 0,
        consents_hard_deleted=con_res.rowcount or 0,
    )


@app.get("/")
def spa_root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"status": "ok", "note": "Frontend not built. This is the API only."}


@app.get("/{path:path}")
def spa_catch_all(path: str):
    api_prefixes = ("session", "alumni", "user", "health", "assets", "docs", "openapi.json",
                    "consent", "me", "admin", "dev")
    if path.startswith(api_prefixes):
        raise HTTPException(404, "Not found")
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(404, "Not found")