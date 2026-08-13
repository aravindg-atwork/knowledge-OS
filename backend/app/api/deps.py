import uuid
from dataclasses import dataclass

from fastapi import Header

from app.core.errors import PermissionDeniedError
from app.core.security import decode_access_token


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    workspace_id: uuid.UUID


def get_current_user(authorization: str = Header(...)) -> CurrentUser:
    if not authorization.startswith("Bearer "):
        raise PermissionDeniedError("Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token)
    except Exception as exc:
        raise PermissionDeniedError("Invalid or expired token") from exc
    return CurrentUser(
        user_id=uuid.UUID(payload["sub"]), workspace_id=uuid.UUID(payload["workspace_id"])
    )
