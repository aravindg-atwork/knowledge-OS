import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUser,
    get_current_user_allow_unverified,
    invalidate_membership_cache,
)
from app.core.audit import log_audit_event
from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidTokenError, PermissionDeniedError, TokenExpiredError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.email.factory import get_email_provider
from app.email.provider import EmailProvider
from app.email.templates import password_reset_message, verify_email_message
from app.models.auth_token import AuthToken, AuthTokenPurpose
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.tenancy_service import TenancyService
from app.services.token_service import generate_token, hash_token, is_expired

router = APIRouter(prefix="/auth", tags=["auth"])

_VERIFY_TTL = timedelta(days=7)
_RESET_TTL = timedelta(hours=1)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    workspace_name: str


class SimpleStatusResponse(BaseModel):
    status: str


class TokenOnlyRequest(BaseModel):
    token: str


class EmailOnlyRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


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


def _issue_verification_email(db: Session, user: User, email_provider: EmailProvider) -> None:
    raw = generate_token()
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=AuthTokenPurpose.verify_email,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + _VERIFY_TTL,
        )
    )
    db.flush()
    link = f"{get_settings().FRONTEND_BASE_URL}/verify-email?token={raw}"
    email_provider.send(verify_email_message(user.email, link))


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(get_settings().RATE_LIMIT_SIGNUP)
def signup(
    request: Request,
    payload: SignupRequest,
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> LoginResponse:
    """Create a new user and their first workspace, then send a verification
    email. Issues an access token immediately -- the account is usable right
    away, but permission-sensitive routes gate on email verification (see
    Task 7's deps.py gate) rather than blocking signup on it.
    """
    repo = WorkspaceRepository(db)
    if repo.get_user_by_email(payload.email) is not None:
        log_audit_event("auth.signup.failure", email=payload.email, reason="email_taken")
        raise ConflictError("An account with that email already exists", code="email_taken")

    # The pre-check above is not atomic with this insert: two concurrent
    # signups for the same address can both pass it and race to insert.
    # users.email carries a DB-level unique constraint, so the loser fails
    # here instead -- caught via a SAVEPOINT (mirroring the discipline in
    # TenancyService.create_workspace's slug race) so only this insert rolls
    # back, not any unrelated work already pending on `db`. Unlike a slug
    # collision, an email collision is terminal -- no retry, just the same
    # clean 409 the non-racy pre-check path returns.
    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    savepoint = db.begin_nested()
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        savepoint.rollback()
        log_audit_event("auth.signup.failure", email=payload.email, reason="email_taken")
        raise ConflictError("An account with that email already exists", code="email_taken")
    savepoint.commit()

    workspace = TenancyService(db).create_workspace(payload.workspace_name, user)
    _issue_verification_email(db, user, email_provider)
    db.commit()

    log_audit_event(
        "auth.signup.success", user_id=str(user.id), workspace_id=str(workspace.id)
    )
    return LoginResponse(access_token=create_access_token(user.id, workspace.id))


@router.post("/verify-email", response_model=SimpleStatusResponse)
def verify_email(payload: TokenOnlyRequest, db: Session = Depends(get_db)) -> SimpleStatusResponse:
    token = db.scalars(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(payload.token),
            AuthToken.purpose == AuthTokenPurpose.verify_email,
        )
    ).first()
    if token is None or token.used_at is not None:
        log_audit_event("auth.email_verify.failure", reason="invalid_token")
        raise InvalidTokenError()
    if is_expired(token.expires_at):
        log_audit_event(
            "auth.email_verify.failure", user_id=str(token.user_id), reason="token_expired"
        )
        raise TokenExpiredError()

    user = db.get(User, token.user_id)
    now = datetime.now(UTC)
    user.email_verified_at = now
    token.used_at = now
    db.commit()

    # api/deps.py caches "role|verified" per (user, workspace) for up to 60s.
    # Verification is a user-level fact, not scoped to one workspace, so a
    # request against ANY workspace this user belongs to could otherwise
    # keep reading the stale "unverified" cache entry for up to 60s after
    # this commit -- exactly the gap that lets the UI say "verified" while
    # the API still 403s with email_not_verified. Invalidate every
    # membership, not just the one active when they signed up.
    for membership in TenancyService(db).list_memberships(user.id):
        invalidate_membership_cache(user.id, membership.workspace_id)

    log_audit_event("auth.email_verify.success", user_id=str(user.id))
    return SimpleStatusResponse(status="verified")


@router.post(
    "/resend-verification",
    response_model=SimpleStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(get_settings().RATE_LIMIT_SIGNUP)
def resend_verification(
    request: Request,
    payload: EmailOnlyRequest,
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> SimpleStatusResponse:
    """Always 202 regardless of whether the address exists -- this endpoint
    must not reveal who has an account."""
    user = WorkspaceRepository(db).get_user_by_email(payload.email)
    if user is not None and user.email_verified_at is None:
        _issue_verification_email(db, user, email_provider)
        db.commit()
    log_audit_event("auth.resend_verification.requested", email=payload.email)
    return SimpleStatusResponse(status="accepted")


@router.post(
    "/forgot-password",
    response_model=SimpleStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(get_settings().RATE_LIMIT_PASSWORD_RESET)
def forgot_password(
    request: Request,
    payload: EmailOnlyRequest,
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> SimpleStatusResponse:
    """Always 202 with an identical body, whether or not the address exists --
    otherwise this endpoint becomes a customer-enumeration oracle."""
    user = WorkspaceRepository(db).get_user_by_email(payload.email)
    if user is not None:
        raw = generate_token()
        db.add(
            AuthToken(
                user_id=user.id,
                purpose=AuthTokenPurpose.password_reset,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + _RESET_TTL,
            )
        )
        db.flush()
        link = f"{get_settings().FRONTEND_BASE_URL}/reset-password?token={raw}"
        email_provider.send(password_reset_message(user.email, link))
        db.commit()
        log_audit_event("auth.password_reset.requested", user_id=str(user.id))
    return SimpleStatusResponse(status="accepted")


@router.post("/reset-password", response_model=SimpleStatusResponse)
def reset_password(
    payload: ResetPasswordRequest, db: Session = Depends(get_db)
) -> SimpleStatusResponse:
    token = db.scalars(
        select(AuthToken).where(
            AuthToken.token_hash == hash_token(payload.token),
            AuthToken.purpose == AuthTokenPurpose.password_reset,
        )
    ).first()
    if token is None or token.used_at is not None:
        raise InvalidTokenError()
    if is_expired(token.expires_at):
        raise TokenExpiredError()

    user = db.get(User, token.user_id)
    user.hashed_password = hash_password(payload.new_password)
    token.used_at = datetime.now(UTC)
    db.commit()

    log_audit_event("auth.password_reset.completed", user_id=str(user.id))
    return SimpleStatusResponse(status="reset")


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    email_verified: bool
    active_workspace_id: str
    role: str
    workspaces: list[WorkspaceSummary]


class SwitchWorkspaceRequest(BaseModel):
    workspace_id: uuid.UUID


@router.get("/me", response_model=MeResponse)
def me(
    current_user: CurrentUser = Depends(get_current_user_allow_unverified),
    db: Session = Depends(get_db),
) -> MeResponse:
    user = db.get(User, current_user.user_id)
    memberships = TenancyService(db).list_memberships(user.id)
    summaries = []
    for membership in memberships:
        workspace = db.get(Workspace, membership.workspace_id)
        summaries.append(
            WorkspaceSummary(
                id=str(workspace.id),
                name=workspace.name,
                slug=workspace.slug,
                role=membership.role.value,
            )
        )
    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        email_verified=user.email_verified_at is not None,
        active_workspace_id=str(current_user.workspace_id),
        role=current_user.role.value,
        workspaces=summaries,
    )


@router.post("/switch-workspace", response_model=LoginResponse)
def switch_workspace(
    payload: SwitchWorkspaceRequest,
    current_user: CurrentUser = Depends(get_current_user_allow_unverified),
    db: Session = Depends(get_db),
) -> LoginResponse:
    # WorkspaceRepository.get_membership takes (workspace_id, user_id), not
    # (user_id, workspace_id) -- verified against
    # app/repositories/workspace_repository.py. Swapping the args wouldn't
    # raise, it would just silently return None forever, so this order is
    # load-bearing for the 403 below.
    membership = WorkspaceRepository(db).get_membership(
        payload.workspace_id, current_user.user_id
    )
    if membership is None:
        raise PermissionDeniedError("You are not a member of that workspace")
    log_audit_event(
        "auth.workspace_switched",
        user_id=str(current_user.user_id),
        workspace_id=str(payload.workspace_id),
    )
    return LoginResponse(
        access_token=create_access_token(current_user.user_id, payload.workspace_id)
    )
