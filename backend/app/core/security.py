from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd_context.verify(password, hashed)


def create_access_token(user_id: UUID, workspace_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "workspace_id": str(workspace_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


_OAUTH_STATE_PURPOSE = "google_oauth_state"


def create_oauth_state_token(workspace_id: UUID, user_id: UUID, connector_type: str) -> str:
    """Short-lived, signed `state` param for the Google OAuth redirect dance.

    The callback endpoint (app/api/v1/connectors.py) is hit by the user's
    browser navigating away from Google -- it has no Authorization header to
    identify the caller with, so who this consent is *for* (which workspace,
    which teammate, which connector type) has to travel inside `state`
    itself, tamper-evident via the same JWT_SECRET used for session tokens.
    user_id matters because each teammate gets their own connector account
    row (see ConnectorAccount.user_id) -- without it the callback couldn't
    tell which of several possible accounts this consent belongs to. A
    distinct `purpose` claim (checked on decode) stops a leaked state value
    from being replayed as a session access token, and vice versa.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "purpose": _OAUTH_STATE_PURPOSE,
        "workspace_id": str(workspace_id),
        "user_id": str(user_id),
        "connector_type": connector_type,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_oauth_state_token(token: str) -> dict:
    settings = get_settings()
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("purpose") != _OAUTH_STATE_PURPOSE:
        raise ValueError("Not an OAuth state token")
    return payload
