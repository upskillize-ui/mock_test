import os
import sys
from dotenv import load_dotenv

load_dotenv()


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
    MODEL_INTERVIEW: str = os.getenv("MODEL_INTERVIEW", "claude-haiku-4-5-20251001")
    MODEL_DEBRIEF: str = os.getenv("MODEL_DEBRIEF", "claude-sonnet-4-6")
    APP_ENV: str = os.getenv("APP_ENV", "production")

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