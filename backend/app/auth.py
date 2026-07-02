from fastapi import Header, HTTPException, status
from jose import jwt, JWTError
from .config import settings


def current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.removeprefix("Bearer ").strip()
    try:
        kwargs = {
            "algorithms": [settings.JWT_ALGORITHM],
            "options": {"require": ["exp"], "verify_exp": True},
        }
        if settings.JWT_AUDIENCE:
            kwargs["audience"] = settings.JWT_AUDIENCE
        if settings.JWT_ISSUER:
            kwargs["issuer"] = settings.JWT_ISSUER
        payload = jwt.decode(token, settings.JWT_SECRET, **kwargs)
    except JWTError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if not user_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return str(user_id)