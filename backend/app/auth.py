import logging

from fastapi import Header, HTTPException, status
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

from .config import settings

log = logging.getLogger(__name__)


def _reject(reason: str, token: str = "", *, generic: str = "Invalid or expired token") -> HTTPException:
    """Build the 401 for a rejected token.

    In non-production we (a) log the SPECIFIC reason at INFO (token truncated to its
    first 12 chars — never logged in full) and (b) put that reason in the response
    `detail`, so the frontend banner can show "Please log in again (token expired)".
    Production returns only the generic message and logs nothing token-specific.
    """
    if settings.APP_ENV != "production":
        log.info("auth: token rejected — %s (token[:12]=%r)", reason, (token or "")[:12])
        detail = reason
    else:
        detail = generic
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def current_user(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise _reject("missing or non-Bearer Authorization header", generic="Authentication required")

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
        raise _reject("token expired (exp is in the past)", token)
    except JWTClaimsError as e:
        # Audience/issuer mismatch, or a required claim failed validation.
        raise _reject(f"claim validation failed: {e}", token)
    except JWTError as e:
        # Signature mismatch (wrong secret — or the token was minted for a DIFFERENT
        # backend), unexpected alg, or a malformed/unparseable token.
        raise _reject(f"decode failed: {e}", token)

    # Enforce our declared intent that exp is mandatory. jose's options={"require":
    # ["exp"]} is a silent no-op in this version (a token with no exp otherwise
    # validates and never expires), so we check explicitly.
    if "exp" not in payload:
        raise _reject("missing required 'exp' claim (token would never expire)", token)

    user_id = payload.get("sub") or payload.get("user_id") or payload.get("id")
    if not user_id:
        raise _reject("no user identifier (sub/user_id/id all absent)", token,
                      generic="Token missing user identifier")

    return str(user_id)
