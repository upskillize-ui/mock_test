from pydantic import BaseModel, Field, model_validator
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
    # "Critical" is the pressure panel — a stress-interview simulator. It is a real genre
    # in Indian hiring (bank PO panels, consulting partners, some PSU boards), and nobody
    # lands in it by accident: the selector requires a second, explicit confirmation tap.
    # It changes the interviewer's REGISTER and raises the curveball count. It does NOT
    # relax a single guardrail — see prompts.build_persona.
    difficulty: Literal["Easy", "Realistic", "Stretch", "Critical"] = "Realistic"
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
    # E2 pacing: per-sentence clips (see TurnResponse.audio_segments). There is no
    # whole-greeting `audio_url` any more — see TurnResponse.
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


class GreetingRequest(BaseModel):
    """FAST START: the room is already on screen — now go and get the greeting."""
    session_id: str = Field(..., max_length=36)
    voice: Literal["female", "male"] = "female"


class GreetingResponse(BaseModel):
    """The interviewer's opening line, and the audio for its FIRST SENTENCE ONLY.

    The rest of the sentences ride back with `pending: true` and no audio_url — the client
    starts playing sentence one immediately and pulls the others from /session/speech while
    it is in the air. Waiting for the whole greeting to synthesise before saying one word
    was most of the 14.5s the founder sat through.
    """
    greeting: str
    audio_segments: list[dict] = []
    tone: str = "warm"
    interviewer_identity: Optional[str] = None


class SpeechRequest(BaseModel):
    """FAST START: 'synthesise the rest of what you just said, from sentence N on.'

    An INDEX, never text. This endpoint cannot be made to read an arbitrary string aloud
    on our bill: it re-derives the sentences server-side from the reply already stored for
    THIS session, so the only thing it can ever synthesise is something this interviewer
    has already said to this candidate.
    """
    session_id: str = Field(..., max_length=36)
    voice: Literal["female", "male"] = "female"
    from_index: int = Field(1, ge=0, le=64)


class SpeechResponse(BaseModel):
    # [{index, audio_url}] — the client merges these into the segments it already has.
    segments: list[dict] = []


class ClipPackResponse(BaseModel):
    """The shared, pre-cached clips the room plays instantly — no LLM, no wait.

    acks         — played the instant an answer is submitted, while the real reply
                   generates. The thinking gap stops sounding like a machine loading.
    backchannels — played softly at a natural pause inside a long answer ("mm-hmm"),
                   so the interviewer sounds like she is still listening.

    Both are [{text, audio_url}]. Empty when TTS is off, and the room is fine with that.
    """
    acks: list[dict] = []
    backchannels: list[dict] = []


class TurnRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    # Empty ONLY for timeout="skip" (the question's clock ran out with nothing captured);
    # the server writes the skip marker itself. Enforced below, so an ordinary empty turn
    # is still rejected.
    message: str = Field("", max_length=4000)
    # INT-04: the stage the client believes it is answering; a mismatch with the
    # server's current_stage is rejected with 409. Optional for backward-compat.
    stage: Optional[str] = Field(None, max_length=20)
    # Voice Phase 1: TTS voice preference for this turn's spoken question.
    voice: Literal["female", "male"] = "female"
    # Voice Phase 3: delivery metrics for a SPOKEN answer, echoed back from the
    # /session/stt response so they persist on this answer's message row. Absent for
    # typed answers. Server re-validates the shape; informational only (not scored).
    delivery_metrics: Optional[dict] = None
    # E7.7: this turn was forced by the per-question clock, not by the candidate pressing
    # send. "partial" — we cut them off mid-answer and submitted what we had. "skip" —
    # nothing at all was captured. Absent on every ordinary turn.
    timeout: Optional[Literal["partial", "skip"]] = None

    @model_validator(mode="after")
    def _message_required_unless_skipped(self):
        if self.timeout != "skip" and not self.message.strip():
            raise ValueError("message must not be empty")
        return self


class TurnResponse(BaseModel):
    reply: str
    answer_id: int
    state: SessionState
    # E2 pacing: ONE clip per sentence — [{text, audio_url, pause_before_ms}] — so the
    # client can hold a human beat between sentences and advance captions in lockstep.
    #
    # The whole-reply `audio_url` that used to ride alongside this is GONE (the 2-call
    # lever). It was the same audio as the segments, billed a second time, and the client
    # only ever played it on the iOS tap-to-play fallback — which now replays the segments
    # instead. Replies are spoken from `audio_segments` and nowhere else. Single short
    # lines (re-ask, mute fork, the rating ask) still carry their own audio_url: they have
    # no segments, and are one clip by nature.
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
    # The engagement floor. "question" on every ordinary turn; "checkin" when the
    # interviewer has broken off the question march to ask whether they are still there.
    # A check-in is a direct question and carries its own short clock — the client reads
    # `checkin_seconds` instead of the round's per-question budget.
    question_kind: str = "question"
    checkin_seconds: int = 45


class ReaskRequest(BaseModel):
    session_id: str = Field(..., max_length=36)
    voice: Literal["female", "male"] = "female"
    # "reask" — the transcription failed, ask them to say it again.
    # "mute"  — the mic is MUTED and an answer is due: offer the unmute-or-type fork.
    # "quiet" — the mic was open but the answer came through near-silent (too quiet/far).
    # "noise" — speech is present but heavy background noise keeps garbling it.
    # None of these insert a message or touch the stage machine, so none costs a slot.
    kind: Literal["reask", "mute", "quiet", "noise"] = "reask"


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
    # camera_off        — the camera ladder reached "wrap" (Phase E device policy).
    # no_answer_timeout — both channels silent for 90s with an answer due (abandonment).
    # session_time_up   — the session clock expired (E7.7): wrap, then score what we have.
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


class SessionProfile(BaseModel):
    """SCORING_CONTEXT item 1: the context every number on the readout is read against.

    No score appears anywhere without this. A band with no context attached is not a
    verdict, it is a compliment — which is exactly how Easy/10min/raw-100 came to read
    stronger than Critical/45min/raw-75.
    """
    role: str = ""
    company: str = ""
    level: str = ""
    difficulty: str = ""
    duration_min: int = 0
    # Reserved: TEXT/VOICE/HYBRID lands with the Intake sprint. None until then, and the
    # strip says so honestly rather than guessing.
    mode: Optional[str] = None
    # interview | coach — the lobby heading now reads FEEDBACK; the column keeps its name.
    feedback: str = "interview"
    rounds_covered: list[str] = []
    rounds_skipped: list[str] = []


class ScoreContext(BaseModel):
    """SCORING_CONTEXT items 2/3/5/8: the benchmark and everything needed to defend it.

    Every field here is STORED per attempt, never recomputed on read — retuning
    scoring.WEIGHTS must not change a score a learner has already been shown.
    """
    # The context-weighted score, display-capped at 100.
    benchmark: int
    # The same maths uncapped. Distinguishes "cleared 100 with room to spare" from "just".
    benchmark_uncapped: float
    # The RAW, level-anchored rubric score. Never re-weighted; coverage never touches it.
    raw: int
    # The band the raw answers EARNED, before any context gate.
    earned_band: str
    # True when a gate capped the band below what the answers earned.
    capped: bool = False
    # The binding gate's ladder copy ("Easy caps at Building. Step up to Realistic…").
    gate_copy: str = ""
    gates: list[dict] = []
    # {difficulty, evidence, feedback, coverage, mode} — the exact multipliers used.
    factors: dict = {}
    # Which release of the weights table scored this attempt.
    weights_version: str = ""
    # "How this score is calculated" — one plain-words row per factor.
    math: list[dict] = []


class DebriefResponse(BaseModel):
    session_id: str
    # INT-03: the readout returns a band, never the raw percentage.
    # SCORING_CONTEXT item 3: this is the band AFTER the context gates — the one and only
    # band the UI renders (item 9: it appears exactly once, in the Readiness block).
    overall_band: str
    round_bands: dict
    one_line: str
    sub_scores: dict
    # E6: a strength is now {strength, evidence} — the mentor quotes them back to
    # themselves. Sessions scored before that change hold plain strings, and history must
    # keep rendering them, so both shapes are valid here.
    strengths: list[dict | str]
    # E6: {gap, cost, tryThisNextTime, upskillizeCourse}. Older rows lack the last two.
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

    # ── SCORING_CONTEXT ──────────────────────────────────────────────────────
    # The context strip. Present on EVERY readout, scored or not.
    profile: SessionProfile = SessionProfile()
    # False when the attempt fell below the evidence floor (< 3 substantive answers).
    # When false there is no band, no benchmark and no tiles — `evidence` says why, and
    # overall_band/score are not to be rendered. Skipped ≠ failed.
    scored: bool = True
    substantive_answers: int = 0
    # {substantive_answers, minimum, copy} when scored is False; {} otherwise.
    evidence: dict = {}
    # The benchmark block. None on an unscored attempt, and on rows debriefed before
    # migration 007 existed (history keeps rendering those from raw + band).
    score: Optional[ScoreContext] = None
    # {days, copy} — when to come back, and why that long.
    reattempt_window: dict = {}
    # Item 11: the stable hand-off to NudgeAI (CareerIQ later). Presence, calibration and
    # focus events are deliberately NOT in here — they are report-only.
    ecopro: dict = {}


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
    # Schema drift, checked once at boot (see app.schema_check). "ok" | "drift".
    # A drifted database still SERVES — every optional column is written defensively — which
    # is exactly why it needs to be visible somewhere a human will look. It deliberately
    # does NOT make `status` degraded: the service is up, it is just quietly doing less than
    # it says it does.
    # (Named schema_STATUS, not `schema`: a field called `schema` shadows BaseModel.schema()
    # and pydantic warns about it — a smell that a future version could turn into a break.)
    schema_status: str = "ok"
    pending_migrations: list[str] = []
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
    # The RAW rubric score. Kept for back-compat and for the detail view; history's TREND
    # reads `benchmark` — a raw score compared across different difficulties and durations
    # is the exact apples-to-oranges this sprint removed from the readout.
    overall: int | None
    one_line: str | None
    # SCORING_CONTEXT item 7. None for an unscored attempt, and for rows debriefed before
    # migration 007 (they have a raw score but never had a benchmark computed).
    benchmark: int | None = None
    band: str | None = None
    # Item 6: False when the attempt fell below the evidence floor. History still SHOWS it
    # — "Ended early — not scored", navy and neutral. Quitting cannot hide a run, and it is
    # never framed as a failure.
    scored: bool = True


class HistoryListResponse(BaseModel):
    sessions: list[HistoryListItem]
    total: int
    # Item 7: the benchmark trend, newest first, and the latest-3 average that any
    # placement view reads instead of a best-ever.
    trend: list[dict] = []
    latest_average: float | None = None


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
    # Student-memory rows past MEMORY_RETENTION_DAYS. Defaulted so an unapplied
    # migration 008 still returns a well-formed response (the purge reports 0 rather
    # than 500-ing the nightly retention job).
    memory_purged: int = 0