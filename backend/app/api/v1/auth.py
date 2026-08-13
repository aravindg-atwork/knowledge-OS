from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit_event
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.workspace import WorkspaceMembership
from app.repositories.workspace_repository import WorkspaceRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=LoginResponse)
@limiter.limit(get_settings().RATE_LIMIT_LOGIN)
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Dev-only credential login issuing a JWT. Real SSO/OAuth login is out
    of scope for this milestone; single-workspace-per-user is assumed.

    Rate-limited (per client IP) to slow down credential-stuffing/brute-force
    attempts against this endpoint -- see RATE_LIMIT_LOGIN.
    """
    repo = WorkspaceRepository(db)
    user = repo.get_user_by_email(payload.email)
    if user is None or not verify_password(payload.password, user.hashed_password):
        log_audit_event("auth.login.failure", email=payload.email, reason="invalid_credentials")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    membership = db.scalars(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)
    ).first()
    if membership is None:
        log_audit_event(
            "auth.login.failure", user_id=str(user.id), reason="no_workspace_membership"
        )
        raise HTTPException(status_code=403, detail="User has no workspace membership")

    token = create_access_token(user.id, membership.workspace_id)
    log_audit_event(
        "auth.login.success", user_id=str(user.id), workspace_id=str(membership.workspace_id)
    )
    return LoginResponse(access_token=token)
