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
    # Voice Phase 2: whether spoken-answer input is available at all (STT_ENABLED
    # AND VOICE_ENABLED). The frontend still shows the mic only in the BEHAVIOURAL
    # round; consent is collected on first mic use. False when either flag is off.
    stt_available: bool = False
    # Interview Room: set once the session has been wrapped early (server-side and
    # persisted, so a refresh can't dodge it). The client routes straight to the readout.
    early_wrap_reason: Optional[str] = None


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
    # Voice Phase 1: TTS voice preference. "female" (default) | "male".
    voice: Literal["female", "male"] = "female"
    # Interview Room: the client's roster (pickInterviewer) chose the FACE the student
    # sees, so it also owns the NAME. The improvised persona adopts it, otherwise the
    # portrait and the voice would introduce themselves as different people. Optional —
    # classic mode omits it and the server draws a name as before.
    interviewer_name: str = Field("", max_length=40)
    # Interview Room: did they JOIN with the camera on? A camera-off join is an
    # accessibility path — camera attention signals are disabled for the whole session
    # and the readout omits camera-based presence lines. Never a penalty.
    camera_at_join: bool = False


class StartSessionResponse(BaseModel):
    session_id: str
    greeting: str
    state: SessionState
    # Voice Phase 1: relative URL to spoken greeting audio; null when TTS is off/failed.
    audio_url: Optional[str] = None
    # E2 pacing: per-sentence clips (see TurnResponse.audio_segments).
    audio_segments: list[dict] = []
    # POSES: the greeting is always warm (see TurnResponse.tone).
    tone: str = "warm"
    # Voice Phase 2: mirror of state.stt_available at the top level so a client that
    # keeps only the session id (not the whole state) can decide to show the mic
    # without a second /state fetch. Source of truth is still state.stt_available.
    stt_available: bool = False
    # Realism v2: the one-line identity the interviewer improvised for this session.
    # Returned in NON-PRODUCTION only, purely so UAT can log it and confirm that fresh
    # sessions really do yield different interviewers. Never rendered in the UI.
    interviewer_identity: Optional[str] = None


class TurnRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    message: str = Field(..., min_length=1, max_length=4000)
    # INT-04: the stage the client believes it is answering; a mismatch with the
    # server's current_stage is rejected with 409. Optional for backward-compat.
    stage: Optional[str] = Field(None, max_length=20)
    # Voice Phase 1: TTS voice preference for this turn's spoken question.
    voice: Literal["female", "male"] = "female"
    # Voice Phase 3: delivery metrics for a SPOKEN answer, echoed back from the
    # /session/stt response so they persist on this answer's message row. Absent for
    # typed answers. Server re-validates the shape; informational only (not scored).
    delivery_metrics: Optional[dict] = None


class TurnResponse(BaseModel):
    reply: str
    answer_id: int
    state: SessionState
    # Voice Phase 1: relative URL to spoken question audio; null when TTS off/failed.
    audio_url: Optional[str] = None
    # E2 pacing: ONE clip per sentence — [{text, audio_url, pause_before_ms}] — so the
    # client can hold a human beat between sentences and advance captions in lockstep.
    audio_segments: list[dict] = []
    # POSES: the register this turn carries — "warm" | "neutral" | "probing". The server
    # decides it (it knows the round and the focus ladder); the client maps it onto the
    # interviewer's pose, so the face and the words say the same thing.
    tone: str = "neutral"
    escalation_level: int = 0
    # Realism v2: when this answer is rating-gated, IQ ASKS for the confidence rating
    # aloud. Present only when state.awaiting_rating is true.
    rating_prompt: Optional[str] = None
    rating_audio_url: Optional[str] = None


class ReaskRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    voice: Literal["female", "male"] = "female"


class ReaskResponse(BaseModel):
    """Realism v2: IQ says 'I didn't catch that' in character and the mic reopens.

    This does NOT insert a message and does NOT touch the stage machine — a failed
    transcription must never consume one of the round's question slots.
    """
    reply: str
    audio_url: Optional[str] = None


class FocusEventRequest(BaseModel):
    """Interview Room: ONE attention/device signal, derived ON-DEVICE.

    Strings and timestamps only. There is deliberately no field here that could carry
    an image, a video frame, or a facial landmark — camera frames never leave the
    browser, and the schema is the enforcement point.
    """
    session_id: str = Field(..., max_length=36)
    # no_face | multiple_faces | looking_away | tab_hidden | window_blur
    #   | camera_off | mic_off      (validated against app.presence.FOCUS_EVENT_TYPES)
    type: str = Field(..., max_length=24)


class FocusEventResponse(BaseModel):
    recorded: bool                      # False when debounced or not applicable
    attention_events: int = 0           # running total for this session
    escalation_level: int = 0           # 0 none | 1 gentle | 2 firm | 3 noted in feedback
    device_action: str = "none"         # none | nudge | warn | wrap


class WrapRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    # camera_off | no_answer_timeout
    reason: str = Field(..., max_length=40)


class WrapResponse(BaseModel):
    """The EARLY_WRAP decision is made and persisted SERVER-side, so a refresh cannot
    dodge it. Scoring is unaffected — the debrief runs over the rounds completed."""
    wrapped: bool
    reason: Optional[str] = None
    state: Optional[SessionState] = None


class EditLastAnswerRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    message: str = Field(..., min_length=1, max_length=4000)


class EditLastAnswerResponse(BaseModel):
    """Correcting a mis-transcribed answer from the transcript drawer. Idempotent:
    re-sending the same text is a no-op. It rewrites the stored answer (so the debrief
    scores what the learner MEANT), but does not re-run the interviewer's reply."""
    updated: bool
    answer_id: Optional[int] = None


class STTResponse(BaseModel):
    """Voice Phase 2: the transcript of a spoken behavioural answer.

    This does NOT submit the turn — the learner reviews/edits the transcript and
    presses Send as normal. `transcript` is None when transcription was
    unavailable or empty, so the client falls back to typing.
    """
    transcript: Optional[str] = None
    # Voice Phase 3: delivery metrics computed from this recording (wpm/fillers/
    # pauses), or null if unavailable. The client echoes this back on /session/turn
    # so it lands on the answer's message row. Audio itself is already discarded.
    delivery_metrics: Optional[dict] = None


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
    # Voice Phase 3 (Part D): aggregated Delivery Profile from spoken answers.
    # {enough_data: false, message} when < 3 spoken answers. Informational — it does
    # NOT affect overall_band in v1.
    delivery: dict = {}
    # Interview Room: Professional presence — COUNTS of attention events + one coaching
    # line. Camera-based lines are omitted entirely for a camera-off join. Informational;
    # it does not move the readiness band.
    professional_presence: dict = {}
    # Set when the interview ended early (e.g. the camera stayed off). Neutral language;
    # the rounds that were completed are still scored normally — nothing is zeroed.
    early_wrap: Optional[str] = None


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