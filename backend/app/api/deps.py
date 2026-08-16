import uuid
from dataclasses import dataclass

import redis
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import EmailNotVerifiedError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.models.workspace import WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository

_MEMBERSHIP_TTL_SECONDS = 60


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: WorkspaceRole
    email_verified: bool


def _cache() -> redis.Redis:
    return redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def _cache_key(user_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
    return f"membership:{user_id}:{workspace_id}"


def invalidate_membership_cache(user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    """Call after any membership or role change so revocation takes effect
    immediately rather than after the TTL."""
    try:
        _cache().delete(_cache_key(user_id, workspace_id))
    except redis.RedisError:
        pass  # cache is an optimisation; the DB remains authoritative


def _resolve_membership(
    db: Session, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[WorkspaceRole, bool]:
    """Returns (role, email_verified). Raises if the membership is gone."""
    key = _cache_key(user_id, workspace_id)
    try:
        cached = _cache().get(key)
    except redis.RedisError:
        cached = None
    if cached:
        role_value, verified_flag = cached.split("|", 1)
        return WorkspaceRole(role_value), verified_flag == "1"

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise PermissionDeniedError("User is not active")
    # NOTE: WorkspaceRepository.get_membership takes (workspace_id, user_id),
    # not (user_id, workspace_id) -- verified against
    # app/repositories/workspace_repository.py before wiring this up.
    membership = WorkspaceRepository(db).get_membership(workspace_id, user_id)
    if membership is None:
        raise PermissionDeniedError("You are not a member of this workspace")

    verified = user.email_verified_at is not None
    try:
        _cache().setex(
            key, _MEMBERSHIP_TTL_SECONDS, f"{membership.role.value}|{'1' if verified else '0'}"
        )
    except redis.RedisError:
        pass
    return membership.role, verified


def _decode_bearer_token(authorization: str) -> dict:
    if not authorization.startswith("Bearer "):
        raise PermissionDeniedError("Missing bearer token")
    token = authorization.removeprefix("Bearer ")
    try:
        return decode_access_token(token)
    except Exception as exc:
        raise PermissionDeniedError("Invalid or expired token") from exc


def get_current_user(
    authorization: str = Header(...), db: Session = Depends(get_db)
) -> CurrentUser:
    payload = _decode_bearer_token(authorization)
    user_id = uuid.UUID(payload["sub"])
    workspace_id = uuid.UUID(payload["workspace_id"])
    role, email_verified = _resolve_membership(db, user_id, workspace_id)
    if not email_verified:
        raise EmailNotVerifiedError()
    return CurrentUser(
        user_id=user_id, workspace_id=workspace_id, role=role, email_verified=email_verified
    )


def get_current_user_allow_unverified(
    authorization: str = Header(...), db: Session = Depends(get_db)
) -> CurrentUser:
    """For the handful of endpoints an unverified user must still reach:
    /auth/me, /auth/switch-workspace, GET /workspaces, /invitations/accept."""
    payload = _decode_bearer_token(authorization)
    user_id = uuid.UUID(payload["sub"])
    workspace_id = uuid.UUID(payload["workspace_id"])
    role, email_verified = _resolve_membership(db, user_id, workspace_id)
    return CurrentUser(
        user_id=user_id, workspace_id=workspace_id, role=role, email_verified=email_verified
    )


def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role is not WorkspaceRole.admin:
        raise PermissionDeniedError(
            "This action requires workspace admin", code="admin_required"
        )
    return current_user
