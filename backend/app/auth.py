import logging

from fastapi import Header, HTTPException, status
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

from .config import settings

log = logging.getLogger(__name__)


def _log_rejection(reason: str, token: str = "") -> None:
    """Dev-only diagnostic: say WHY a token was rejected, at INFO, in non-prod.

    Never logs the token in full — at most its first 12 chars (enough to correlate
    with what the client sent, not enough to reuse). Silent in production so we don't
    leak auth internals or token fragments into prod logs.
    """
    if settings.APP_ENV == "production":
        return
    prefix = (token or "")[:12]
    log.info("auth: token rejected — %s (token[:12]=%r)", reason, prefix)


def current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        _log_rejection("missing or non-Bearer Authorization header")
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
    except ExpiredSignatureError:
        _log_rejection("expired (exp is in the past)", token)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTClaimsError as e:
        # Audience/issuer mismatch, or a required claim failed validation.
        _log_rejection(f"claim validation failed: {e}", token)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        # Signature mismatch (wrong secret), unexpected alg, missing required claim,
        # or a malformed/unparseable token — the message says which.
        _log_rejection(f"decode failed: {e}", token)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce our declared intent that exp is mandatory. jose's options={"require":
    # ["exp"]} is a silent no-op in this version (a token with no exp otherwise
    # validates and never expires), so we check explicitly.
    if "exp" not in payload:
        _log_rejection("missing required 'exp' claim (token would never expire)", token)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if not user_id:
        _log_rejection("no user identifier (sub/user_id/id all absent)", token)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Token missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return str(user_id)
