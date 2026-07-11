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
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_AUDIENCE: str = os.getenv("JWT_AUDIENCE", "")
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "")
    MAX_SESSIONS_PER_DAY: int = int(os.getenv("MAX_SESSIONS_PER_DAY", "10"))
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
    # Voice Phase 3: ask Saarika for word/segment timestamps (same call, no extra
    # cost) so delivery scoring can flag long mid-answer pauses. Off = pauses null.
    STT_WITH_TIMESTAMPS: bool = _env_bool("STT_WITH_TIMESTAMPS", "true")
    # Voice Phase 3: compute-and-discard delivery metrics (wpm/fillers/pauses) for
    # spoken answers. OFF by default; independent of STT so it can be piloted alone.
    DELIVERY_METRICS_ENABLED: bool = _env_bool("DELIVERY_METRICS_ENABLED")

    RESUME_HOST_ALLOWLIST: list[str] = [
        h.strip().lower()
        for h in os.getenv("RESUME_HOST_ALLOWLIST", "res.cloudinary.com").split(",")
        if h.strip()
    ]

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