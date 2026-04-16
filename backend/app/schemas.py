from pydantic import BaseModel, Field
from typing import Literal


class StartSessionRequest(BaseModel):
    name: str = ""
    role: str
    level: Literal["Fresher", "1–3 years", "3+ years", "MBA", "Career switcher"]
    company: str = ""
    duration_min: int = Field(20, ge=5, le=60)
    difficulty: Literal["Easy", "Realistic", "Stretch"] = "Realistic"
    mode: Literal["interview", "coach"] = "interview"
    focus: list[str] = []
    intro: str = ""


class StartSessionResponse(BaseModel):
    session_id: str
    greeting: str


class TurnRequest(BaseModel):
    session_id: str
    message: str


class TurnResponse(BaseModel):
    reply: str
    turn_count: int


class EndRequest(BaseModel):
    session_id: str


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
    company: str
    role: str
    city: str = ""
    round_type: str
    question: str
    interview_date: str | None = None  # YYYY-MM-DD


class HealthResponse(BaseModel):
    status: str
    model_interview: str
    model_debrief: str
