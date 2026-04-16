import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    MAX_SESSIONS_PER_DAY: int = int(os.getenv("MAX_SESSIONS_PER_DAY", "10"))
    MODEL_INTERVIEW: str = os.getenv("MODEL_INTERVIEW", "claude-haiku-4-5-20251001")
    MODEL_DEBRIEF: str = os.getenv("MODEL_DEBRIEF", "claude-sonnet-4-6")

    # Claude API endpoint
    ANTHROPIC_URL: str = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION: str = "2023-06-01"


settings = Settings()
