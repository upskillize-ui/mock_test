import os
import sys
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: str = "false") -> bool:
    """Parse an env var as a boolean, tolerant of case and stray whitespace.

    `.strip()` guards against the classic footgun where `VOICE_ENABLED=true ` (a
    trailing space or an inline comment) silently parses as False and a feature
    never turns on. Accepts 1/true/yes/on.
    """
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # .strip() at load: a trailing newline on the Space secret is an invalid header value and
    # httpx rejects it, taking every model call — and therefore the whole product — down. Strip
    # it once here so no caller can inherit the whitespace (claude_client also strips at the
    # header, as a second line of defence).
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "")
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "")
    # INT-09: daily interview cap, PER STUDENT PER DAY (keyed on user id + day, as today).
    # The production cost-abuse guard. Bypassed entirely when APP_ENV=development so
    # local UAT never stalls — see main._check_rate_limit.
    MAX_SESSIONS_PER_DAY: int = int(os.getenv("MAX_SESSIONS_PER_DAY", "20"))
    MAX_ALUMNI_PER_DAY: int = int(os.getenv("MAX_ALUMNI_PER_DAY", "5"))
    # INT-04: hard cap on answered questions per session (spec math + buffer).
    MAX_ANSWERS_PER_SESSION: int = int(os.getenv("MAX_ANSWERS_PER_SESSION", "20"))

    # INT-03: readiness band thresholds (configurable, not hardcoded in logic).
    # Not Ready < BUILDING_MIN; Building < INTERVIEW_READY_MIN;
    # Interview-Ready < OFFER_READY_MIN; Offer-Ready >= OFFER_READY_MIN.
    BAND_BUILDING_MIN: int = int(os.getenv("BAND_BUILDING_MIN", "50"))
    BAND_INTERVIEW_READY_MIN: int = int(os.getenv("BAND_INTERVIEW_READY_MIN", "70"))
    BAND_OFFER_READY_MIN: int = int(os.getenv("BAND_OFFER_READY_MIN", "85"))
    MODEL_INTERVIEW: str = os.getenv("MODEL_INTERVIEW", "claude-haiku-4-5-20251001")
    MODEL_DEBRIEF: str = os.getenv("MODEL_DEBRIEF", "claude-sonnet-4-6")
    APP_ENV: str = os.getenv("APP_ENV", "production")

    # INT-07 (DPDPA): retention windows. Env-overridable; values still need a
    # LEGAL sign-off before go-live (see PHASE0_COMPLETION_REPORT.md).
    TRANSCRIPT_RETENTION_DAYS: int = int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "90"))
    DEBRIEF_RETENTION_DAYS: int = int(os.getenv("DEBRIEF_RETENTION_DAYS", "365"))
    # Right-to-erasure recovery grace: soft-delete now, hard-delete after N days.
    DELETE_GRACE_DAYS: int = int(os.getenv("DELETE_GRACE_DAYS", "30"))
    # Student memory (migration 008) retention. DELIBERATELY LONGER than the transcript
    # window: this table exists so the interviewer does not repeat a greeting it used a
    # year ago, so purging it on the transcript's 90-day clock would defeat the feature
    # while still holding the data for 90 days — the worst of both. Its own window, and
    # it needs the same LEGAL sign-off as the other two before go-live.
    MEMORY_RETENTION_DAYS: int = int(os.getenv("MEMORY_RETENTION_DAYS", "365"))
    # INT-06 resume: an active session idle this long is offered as resume-or-restart.
    SESSION_IDLE_MINUTES: int = int(os.getenv("SESSION_IDLE_MINUTES", "30"))

    # INT-07: voice mode is DPDPA-sensitive and OFF for this sprint. The consent
    # gate is built now and enforced only once this flag flips true.
    VOICE_ENABLED: bool = _env_bool("VOICE_ENABLED")

    # INT-07: shared secret guarding the /admin/purge endpoint (cron-callable).
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
    # TTL of the two-step data-deletion confirmation token.
    DELETE_TOKEN_TTL_SECONDS: int = int(os.getenv("DELETE_TOKEN_TTL_SECONDS", "600"))

    # ── Voice Phase 1: TTS (interviewer speaks; learner still types) ──────────
    # Independent of VOICE_ENABLED (that flag gates future STT/mic consent).
    # TTS is output-only: no mic, no recording, no consent required.
    #
    # Upgraded to Bulbul v3 (v2 voices were legacy/low quality). v3 auto-preprocesses
    # English + numerics, supports temperature and higher sample rates, and does NOT
    # accept pitch/loudness. Speakers are the v3 catalog (lowercase); the old v2
    # speakers (anushka/abhilash) fail on v3, so they are removed.
    SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
    TTS_ENABLED: bool = _env_bool("TTS_ENABLED")
    TTS_MODEL: str = os.getenv("TTS_MODEL", "bulbul:v3")
    TTS_LANG: str = os.getenv("TTS_LANG", "en-IN")
    # Sarvam v3 speaker ids per gender preference (default female). Env-overridable.
    TTS_VOICE_FEMALE: str = os.getenv("TTS_VOICE_FEMALE", "ritu")
    TTS_VOICE_MALE: str = os.getenv("TTS_VOICE_MALE", "shubh")
    TTS_CACHE_DIR: str = os.getenv("TTS_CACHE_DIR", "tts_cache")
    # v3 delivery tuning. temperature=0.4 → stable, professional read; pace=1.0
    # natural. speech_sample_rate 44100 (v3 REST supports up to 48000). mp3 output.
    TTS_TEMPERATURE: float = float(os.getenv("TTS_TEMPERATURE", "0.4"))
    TTS_PACE: float = float(os.getenv("TTS_PACE", "1.0"))
    TTS_SAMPLE_RATE: int = int(os.getenv("TTS_SAMPLE_RATE", "44100"))
    # Optional Sarvam pronunciation-dictionary id (future BFSI-terms dictionary).
    # When set, it is passed as dict_id on every synth call; empty = omitted.
    TTS_DICT_ID: str = os.getenv("TTS_DICT_ID", "")

    # ── Persona/Warmth: Nia's voice (the SENIOR interviewer, 40+) ─────────────
    # Nia reads lower and slightly slower than Nova. Two knobs, both real, both
    # tunable from the Space settings with no code change — see tts.Voice.
    #
    # THERE IS NO PITCH KNOB, AND THAT IS NOT AN OMISSION.
    #   `pitch` is a bulbul:v2 parameter. On v3 (TTS_MODEL, above) it is IGNORED by the
    #   vendor. A NIA_PITCH env var would therefore be a dial wired to nothing: ops would
    #   audition a pitch, set it here, restart, and hear precisely the same audio — with
    #   no error to explain why. So "lower pitch" is expressed the only way v3 can
    #   actually express it: by CHOOSING A LOWER-PITCHED SPEAKER.
    #
    # NIA_SPEAKER is that choice. v3 ships ~14 female speakers; audition them in the
    # Sarvam playground and pin the winner here. Defaults to TTS_VOICE_FEMALE so an
    # existing deploy that sets neither keeps the voice it already had.
    NIA_SPEAKER: str = os.getenv("NIA_SPEAKER", "").strip() or TTS_VOICE_FEMALE
    # Spec: ~0.9-0.95. Slower than Nova's 1.0 — an unhurried read is most of what
    # "calm authority" actually sounds like.
    NIA_PACE: float = float(os.getenv("NIA_PACE", "0.93"))

    # ── Voice Phase 2: STT (learner speaks their answer; BEHAVIOURAL round only) ──
    # OFF by default. Additionally gated at runtime by VOICE_ENABLED + a
    # voice_recording consent row (the INT-07 consent machinery). Reuses
    # SARVAM_API_KEY. No raw audio is ever stored — transcribe-and-discard.
    STT_ENABLED: bool = _env_bool("STT_ENABLED")
    STT_MODEL: str = os.getenv("STT_MODEL", "saarika:v2.5")
    # "unknown" asks Saarika to auto-detect (Hinglish / en-IN / regional). Ops can
    # pin "en-IN" for a stricter English bias.
    STT_LANGUAGE: str = os.getenv("STT_LANGUAGE", "unknown")
    # Hard cap on a single uploaded answer, in bytes (spec: 10 MB).
    STT_MAX_UPLOAD_BYTES: int = int(os.getenv("STT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    # Extra STT attempts allowed beyond the behavioural question count (retries).
    STT_RETRY_ALLOWANCE: int = int(os.getenv("STT_RETRY_ALLOWANCE", "3"))
    # Item 6 (live self-captions): a SEPARATE, generous per-session cap on the short
    # rolling-window partial transcriptions that drive the live "You:" caption. Counted
    # apart from answer STT so a caption never eats an answer's allowance; a safety backstop
    # only — the client already caps windows per answer. Set to 0 to disable partials.
    STT_PARTIAL_MAX_PER_SESSION: int = int(os.getenv("STT_PARTIAL_MAX_PER_SESSION", "400"))
    # Voice Phase 3: ask Saarika for word/segment timestamps (same call, no extra
    # cost) so delivery scoring can flag long mid-answer pauses. Off = pauses null.
    STT_WITH_TIMESTAMPS: bool = _env_bool("STT_WITH_TIMESTAMPS", "true")
    # DIAGNOSTIC (voice-reliability): when a Saarika 200 comes back with no usable
    # transcript, dump the raw (redacted, truncated) response body so ops can see
    # EXACTLY what the vendor returned for a "couldn't hear you on real speech" turn.
    # OFF by default: redact() only scrubs emails/phones, so a body dump could echo
    # transcript words — turn this on only for a controlled live capture window, then
    # off. The always-on `stt_body_shape` line (keys + value lengths, never words) is
    # enough to tell a genuinely-blank body apart from a parser-shape miss.
    STT_DEBUG_BODY: bool = _env_bool("STT_DEBUG_BODY")
    # Voice Phase 3: compute-and-discard delivery metrics (wpm/fillers/pauses) for
    # spoken answers. OFF by default; independent of STT so it can be piloted alone.
    DELIVERY_METRICS_ENABLED: bool = _env_bool("DELIVERY_METRICS_ENABLED")

    # ── Phase D: presence metrics m1–m8 (on-device expression/posture) ────────
    # SHIPS DARK. This flag stays FALSE until the camera/attention-cue consent block
    # has cleared LEGAL review — that is the only thing that turns m1–m8 on for
    # students (see PRESENCE gate, D7). With it false the feature is built, tested and
    # inert: the client never loads MediaPipe, /session/presence 404s, and no metric
    # is ever computed, stored, or shown. Presence metrics are report-only and run in
    # VIDEO mode only; flipping this flag changes no score and no band, ever.
    PRESENCE_METRICS_ENABLED: bool = _env_bool("PRESENCE_METRICS_ENABLED")

    # Realism v2: PATCH /session/turn/last — lets a learner correct a mis-transcribed
    # answer from the transcript drawer. ON by default (the drawer edit depends on it);
    # set false to remove the endpoint entirely (404). No schema impact — it rewrites
    # vyom_messages.content in place and does NOT re-run the interviewer's reply.
    EDIT_LAST_ANSWER_ENABLED: bool = _env_bool("EDIT_LAST_ANSWER_ENABLED", "true")

    RESUME_HOST_ALLOWLIST: list[str] = [
        h.strip().lower()
        for h in os.getenv("RESUME_HOST_ALLOWLIST", "res.cloudinary.com").split(",")
        if h.strip()
    ]

    # ── Attention call-outs: rare, late, gentle, never in warm-up ────────────
    # The interviewer raising "your attention drifted" was firing on the FIRST tab-switch and
    # then again on every subsequent turn — nagging. These make it rare and calm:
    #   * OFF during WARMUP entirely (never police a settling-in student).
    #   * at most ONCE per session (an in-process guard in main._presence_note).
    #   * only after ATTENTION_MIN_EVENTS accumulated attention signals (so a single glance
    #     away never trips it), and only ever in the GENTLE register — the firmer "in a real
    #     panel this costs you" copy is retired from the in-session path (it belongs, if
    #     anywhere, in the post-interview readout, not as a live interruption).
    ATTENTION_CALLOUTS_ENABLED: bool = _env_bool("ATTENTION_CALLOUTS_ENABLED", "true")
    ATTENTION_MIN_EVENTS: int = int(os.getenv("ATTENTION_MIN_EVENTS", "4"))

    # ── Capacity/Cost phase: the safety valve (item 5) ───────────────────────
    # Hard ceiling on CONCURRENT live interviews on this instance. 0 = unlimited (the
    # feature is inert until ops sets a real number from item 4's measured knee). Beyond the
    # cap /session/start returns a polite, in-brand HOLD (503) — never an error, and sessions
    # already running are never touched. See main._check_capacity.
    MAX_CONCURRENT_SESSIONS: int = int(os.getenv("MAX_CONCURRENT_SESSIONS", "0"))
    # The exact hold copy — legal/brand-approved, one line, never styled as an error. Env-
    # overridable so ops can retune wording without a deploy.
    CAPACITY_FULL_MESSAGE: str = os.getenv(
        "CAPACITY_FULL_MESSAGE",
        "Every panel is in session right now. Give us a few minutes — your seat is coming.",
    )
    # A session left 'active' forever (tab closed, no /session/end) must not wedge the cap
    # permanently. Only sessions started within this window count toward "live" concurrency —
    # comfortably longer than the longest interview (45 min) plus its debrief. A stale 'active'
    # row past this window is treated as gone for capacity purposes (its status is fixed lazily
    # on the next end/abandon it ever gets).
    CONCURRENCY_ACTIVE_WINDOW_MINUTES: int = int(os.getenv("CONCURRENCY_ACTIVE_WINDOW_MINUTES", "75"))

    # ── Capacity/Cost phase: the cost ledger rates (item 2) ──────────────────
    # These are the INPUTS the cost report is required to state, and they move with the
    # vendor plan and the forex rate — so they are config, not constants, and ledger.py
    # echoes the exact values it used back into every stored ledger. Defaults are marked and
    # MUST be confirmed against the live Anthropic invoice / Sarvam dashboard before the
    # numbers are quoted to finance (see docs/CAPACITY_COST_REPORT.md §rates).
    USD_TO_INR: float = float(os.getenv("USD_TO_INR", "88.0"))
    SARVAM_CREDIT_TO_INR: float = float(os.getenv("SARVAM_CREDIT_TO_INR", "1.0"))
    # Sarvam bills AUDIO. Bulbul (TTS) and Saarika (STT) credit-per-second rates from the
    # plan. Placeholder defaults — set from the dashboard before quoting.
    SARVAM_TTS_CREDITS_PER_SEC: float = float(os.getenv("SARVAM_TTS_CREDITS_PER_SEC", "0.5"))
    SARVAM_STT_CREDITS_PER_SEC: float = float(os.getenv("SARVAM_STT_CREDITS_PER_SEC", "0.5"))

    # ── Capacity/Cost phase: DB pool sizing (item 6) ─────────────────────────
    # The Space shares one Aiven MySQL with the LMS, and a request holds its pooled
    # connection across the multi-second LLM await (the read transaction opens on the first
    # SELECT and stays open until the turn's final commit). So the pool ceiling — pool_size +
    # max_overflow — is a hard cap on concurrent LLM-bearing requests, and every connection
    # the Space can open is one the LMS cannot. These are ENV-CONFIGURABLE (they were hard-
    # coded 5/10) precisely so ops can right-size them against Aiven's measured connection
    # limit MINUS the LMS's headroom, without a code change — see docs/CAPACITY_COST_REPORT.md
    # §DB pool. Defaults preserve the historical 5 + 10 = 15 ceiling.
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    # Seconds a request waits for a free pooled connection before giving up (SQLAlchemy
    # default is 30). Kept modest so a saturated pool fails fast and visibly rather than
    # hanging every request behind the same wall.
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "15"))
    # Recycle below Aiven's idle-connection timeout so a long-idle pooled connection is not
    # handed out already-dead. 280s was the historical value.
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "280"))

    ANTHROPIC_URL: str = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION: str = "2023-06-01"


settings = Settings()


def validate_settings() -> None:
    errors = []
    if not settings.ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set")
    if not settings.DATABASE_URL:
        errors.append("DATABASE_URL is not set")
    if not settings.JWT_SECRET or settings.JWT_SECRET == "dev-secret-change-me":
        errors.append("JWT_SECRET must be set to a strong secret (not the placeholder)")
    if settings.APP_ENV == "production" and not settings.ALLOWED_ORIGINS:
        errors.append("ALLOWED_ORIGINS must be configured in production")

    if errors:
        for e in errors:
            print(f"[InterviewIQ] CONFIG ERROR: {e}", file=sys.stderr)
        raise RuntimeError("InterviewIQ misconfigured — see errors above")


validate_settings()