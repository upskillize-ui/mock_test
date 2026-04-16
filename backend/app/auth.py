from fastapi import Header, HTTPException, status
from jose import jwt, JWTError
from .config import settings


def current_user(authorization: str | None = Header(default=None)) -> str:
    """
    Extract user_id from Bearer JWT (issued by your LMS).
    Falls back to 'guest-<token>' for anonymous demo use so Vyom works
    even before you wire SSO — remove the fallback for production.
    """
    if not authorization:
        # Anonymous demo mode — comment this block out to force auth
        return "guest-anonymous"

    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad auth header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing user id")

    return str(user_id)
