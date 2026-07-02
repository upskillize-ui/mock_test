from pydantic import BaseModel, Field
from typing import Literal, Annotated, Optional
from datetime import date, datetime


class SessionState(BaseModel):
    """INT-04: the backend is the single source of truth for interview progress.

    INT-06: status/started_at/stale are populated by GET /session/{id}/state so the
    frontend can resume after a refresh. They are optional (default None/False) so
    the lighter start/turn/rating responses can omit them.
    """
    current_stage: str
    round_index: int
    stage_total: int
    awaiting_rating: bool
    last_answer_id: Optional[int] = None
    answer_count: int
    answer_cap: int
    next_action: str  # answer | rating | reverse_question | readout | done
    stage_label: str
    # INT-06 resume fields.
    status: Optional[str] = None            # active | completed | abandoned
    started_at: Optional[datetime] = None
    stale: bool = False                     # active but idle > 30 min


class SessionMessagesResponse(BaseModel):
    """INT-06: full message history for an active session, for post-refresh resume."""
    session_id: str
    messages: list[dict]


class StartSessionRequest(BaseModel):
    name: str = Field("", max_length=120)
    role: str = Field(..., max_length=120)
    level: Literal["Fresher", "1-3 years", "3-10 years", "10-20 years", "20+ years", "Career switcher"]
    company: str = Field("", max_length=120)
    duration_min: int = Field(20, ge=5, le=60)
    difficulty: Literal["Easy", "Realistic", "Stretch"] = "Realistic"
    mode: Literal["interview", "coach"] = "interview"
    round: Literal["screening", "technical", "leadership", "hr", "full"] = "full"
    round_label: str = Field("", max_length=80)
    round_detail: str = Field("", max_length=1000)
    focus: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=10)
    intro: str = Field("", max_length=8000)


class StartSessionResponse(BaseModel):
    session_id: str
    greeting: str
    state: SessionState


class TurnRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    message: str = Field(..., min_length=1, max_length=4000)
    # INT-04: the stage the client believes it is answering; a mismatch with the
    # server's current_stage is rejected with 409. Optional for backward-compat.
    stage: Optional[str] = Field(None, max_length=20)


class TurnResponse(BaseModel):
    reply: str
    answer_id: int
    state: SessionState


class RatingRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    answer_id: int
    # INT-01: 1-5, or null for "prefer not to say".
    rating: Optional[int] = Field(None, ge=1, le=5)


class RatingResponse(BaseModel):
    accepted: bool
    state: SessionState


class EndRequest(BaseModel):
    session_id: str = Field(..., max_length=36)


class DebriefResponse(BaseModel):
    session_id: str
    # INT-03: the readout returns a band, never the raw percentage.
    overall_band: str
    round_bands: dict
    one_line: str
    sub_scores: dict
    strengths: list[str]
    gaps: list[dict]
    star_breakdown: list[dict]
    interviewer_thoughts: list[dict]
    plan: list[str]
    next_focus: str
    # INT-02: calibration profile block.
    calibration: dict


class AlumniQuestionSubmit(BaseModel):
    company: str = Field(..., max_length=120)
    role: str = Field(..., max_length=120)
    city: str = Field("", max_length=80)
    round_type: str = Field(..., max_length=40)
    question: str = Field(..., min_length=10, max_length=2000)
    interview_date: date | None = None


class HealthResponse(BaseModel):
    status: str
    db: str
    model_interview: str
    model_debrief: str


class HistoryListItem(BaseModel):
    session_id: str
    role: str
    company: str
    level: str
    difficulty: str
    mode: str
    round: str
    round_label: str
    focus: list[str]
    planned_duration_min: int
    actual_duration_seconds: int | None
    user_message_count: int
    assistant_message_count: int
    started_at: datetime
    ended_at: datetime | None
    status: str
    completion_type: str | None
    overall: int | None
    one_line: str | None


class HistoryListResponse(BaseModel):
    sessions: list[HistoryListItem]
    total: int


class HistoryDetailResponse(BaseModel):
    session: HistoryListItem
    messages: list[dict]
    debrief: dict | None


# ── INT-07: DPDPA consent + data-rights schemas ─────────────────────────────

class ConsentRequest(BaseModel):
    # e.g. "voice_recording", "data_processing". Free-form so legal can add types
    # without a code change; the copy_version pins which wording was shown.
    consent_type: str = Field(..., max_length=40)
    copy_version: str = Field(..., max_length=40)
    session_id: Optional[str] = Field(None, max_length=36)


class ConsentResponse(BaseModel):
    accepted: bool
    consent_type: str
    copy_version: str


class DeleteRequestResponse(BaseModel):
    # Two-step erasure: step 1 returns a short-lived signed token the client must
    # echo back to confirm. Nothing is deleted at this step.
    confirmation_token: str
    expires_in_seconds: int
    message: str


class DeleteConfirmRequest(BaseModel):
    confirmation_token: str = Field(..., max_length=2000)


class DeleteConfirmResponse(BaseModel):
    deleted: bool
    message: str


class PurgeResponse(BaseModel):
    messages_purged: int
    debriefs_purged: int
    sessions_hard_deleted: int
    consents_hard_deleted: int