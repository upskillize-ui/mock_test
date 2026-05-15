from pydantic import BaseModel, Field
from typing import Literal
from datetime import date, datetime


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
    focus: list[str] = Field(default_factory=list, max_length=10)
    intro: str = Field("", max_length=8000)


class StartSessionResponse(BaseModel):
    session_id: str
    greeting: str


class TurnRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    message: str = Field(..., min_length=1, max_length=4000)


class TurnResponse(BaseModel):
    reply: str
    turn_count: int


class EndRequest(BaseModel):
    session_id: str = Field(..., max_length=36)


class DebriefResponse(BaseModel):
    session_id: str
    overall: int
    one_line: str
    sub_scores: dict
    strengths: list[str]
    gaps: list[dict]
    star_breakdown: list[dict]
    interviewer_thoughts: list[dict]
    plan: list[str]
    next_focus: str


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