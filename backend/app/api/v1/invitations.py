import uuid

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, invalidate_membership_cache, require_admin
from app.core.audit import log_audit_event
from app.core.config import get_settings
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.rate_limit import limiter
from app.core.security import create_access_token, decode_access_token, hash_password
from app.db.session import get_db
from app.email.factory import get_email_provider
from app.email.provider import EmailProvider
from app.email.templates import invite_message
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.invitation_service import InvitationService
from app.services.tenancy_service import TenancyService

router = APIRouter(prefix="/invitations", tags=["invitations"])


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.member


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    expires_at: str


class InvitationPreviewResponse(BaseModel):
    workspace_name: str
    email: str


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str | None = None
    full_name: str | None = None


class AcceptInvitationResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(get_settings().RATE_LIMIT_INVITE)
def create_invitation(
    request: Request,
    payload: CreateInvitationRequest,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
    email_provider: EmailProvider = Depends(get_email_provider),
) -> InvitationResponse:
    service = InvitationService(db)
    invitation, raw = service.create(
        current_user.workspace_id, payload.email, payload.role, current_user.user_id
    )
    inviter = db.get(User, current_user.user_id)
    link = f"{get_settings().FRONTEND_BASE_URL}/invite/accept?token={raw}"
    email_provider.send(
        invite_message(payload.email, service.workspace_name(invitation), inviter.email, link)
    )
    db.commit()
    log_audit_event(
        "invitation.created",
        actor_user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
        email=payload.email,
    )
    return InvitationResponse(
        id=str(invitation.id),
        email=invitation.email,
        role=invitation.role.value,
        expires_at=invitation.expires_at.isoformat(),
    )


@router.get("", response_model=list[InvitationResponse])
def list_invitations(
    current_user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
) -> list[InvitationResponse]:
    invitations = db.scalars(
        select(Invitation).where(
            Invitation.workspace_id == current_user.workspace_id,
            Invitation.accepted_at.is_(None),
        )
    ).all()
    return [
        InvitationResponse(
            id=str(i.id), email=i.email, role=i.role.value, expires_at=i.expires_at.isoformat()
        )
        for i in invitations
    ]


# NOTE: /preview is registered before /{invitation_id} -- FastAPI matches
# routes in registration order, and a path parameter route registered first
# would try (and fail) to parse the literal "preview" as a UUID, returning
# 422 instead of ever reaching this handler.
@router.get("/preview", response_model=InvitationPreviewResponse)
@limiter.limit(get_settings().RATE_LIMIT_INVITE_PREVIEW)
def preview_invitation(
    request: Request, token: str, db: Session = Depends(get_db)
) -> InvitationPreviewResponse:
    """Unauthenticated: the invitee has no account yet, so the accept page
    needs to name the workspace before any login is possible. Reveals only
    the workspace name and the address the invite was already sent to --
    never the inviter, member list, or anything else about the workspace.

    Rate-limited (per client IP) because this endpoint is an unauthenticated
    token-consuming oracle -- without a limit, invite tokens (32 random
    bytes, but still) would be brute-forceable at unlimited rate from any IP.
    """
    service = InvitationService(db)
    invitation = service.find_valid(token)
    return InvitationPreviewResponse(
        workspace_name=service.workspace_name(invitation), email=invitation.email
    )


@router.post("/accept", response_model=AcceptInvitationResponse)
@limiter.limit(get_settings().RATE_LIMIT_INVITE_PREVIEW)
def accept_invitation(
    request: Request,
    payload: AcceptInvitationRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> AcceptInvitationResponse:
    """Authorization is optional: an invitee with no account yet posts a
    password and full_name to create one instead of authenticating. When a
    session *is* present it must belong to the invited address -- otherwise
    the membership would silently attach to whichever account is currently
    logged in, rather than the address the invite was sent to.

    Rate-limited for the same reason as /preview: this is an unauthenticated
    token-consuming endpoint.

    A present-but-broken bearer token (malformed, expired, wrong signature)
    is treated as a *hard* failure, not as "no session" -- it must not
    silently fall through to the anonymous path. If it did, a caller could
    bypass the mismatch check below just by sending garbage instead of a
    valid session token. The try/except is scoped to the decode call only so
    unrelated bugs later in this function are never mistaken for a bad
    token.

    If the invited address already has an account, `payload.password` is
    never used to authenticate it -- posting a password there would let
    anyone who merely intercepts/guesses the invite token log straight into
    an existing account, no credentials required (spec: "Account exists ->
    link opens login, then creates the membership"). So an existing account
    with no matching session gets a clean 403 (login_required) instead of a
    minted token; only a session already authenticated as that exact address
    is allowed to complete acceptance.
    """
    service = InvitationService(db)
    invitation = service.find_valid(payload.token)

    has_matching_session = False
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer "))
        except Exception:
            raise PermissionDeniedError(
                "Invalid or expired session; sign out and open the invitation link again",
                code="invalid_session",
            )
        session_user = db.get(User, uuid.UUID(claims["sub"]))
        if session_user is not None and session_user.email != invitation.email:
            raise PermissionDeniedError(
                "This invitation was sent to a different email address",
                code="invite_email_mismatch",
            )
        has_matching_session = session_user is not None

    user = WorkspaceRepository(db).get_user_by_email(invitation.email)
    if user is None:
        if not payload.password:
            raise PermissionDeniedError(
                "A password is required to create your account", code="password_required"
            )
        user = User(
            email=invitation.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
        )
        db.add(user)
        db.flush()
    elif not has_matching_session:
        raise PermissionDeniedError(
            "An account with that email already exists. Sign in, then open this "
            "invitation link again to join the workspace.",
            code="login_required",
        )

    service.accept(invitation, user)
    db.commit()

    # invitation_service.accept() may set email_verified_at on an existing,
    # previously-unverified user (receiving the invite at that address
    # proves ownership of it). api/deps.py caches "role|verified" per
    # (user, workspace) for up to 60s -- if that user already belongs to
    # other workspaces, a request against any of them could otherwise keep
    # reading a stale "unverified" cache entry. list_memberships is read
    # after the commit above so it also picks up the membership this call
    # just created.
    for membership in TenancyService(db).list_memberships(user.id):
        invalidate_membership_cache(user.id, membership.workspace_id)

    log_audit_event(
        "invitation.accepted",
        user_id=str(user.id),
        workspace_id=str(invitation.workspace_id),
    )
    return AcceptInvitationResponse(
        access_token=create_access_token(user.id, invitation.workspace_id)
    )


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(
    invitation_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.workspace_id != current_user.workspace_id:
        raise NotFoundError("Invitation not found")
    db.delete(invitation)
    db.commit()
    log_audit_event(
        "invitation.revoked",
        actor_user_id=str(current_user.user_id),
        workspace_id=str(current_user.workspace_id),
    )
