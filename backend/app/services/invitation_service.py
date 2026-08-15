import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, InvalidTokenError, TokenExpiredError
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.token_service import generate_token, hash_token, is_expired

INVITE_TTL = timedelta(days=7)


class InvitationService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _pending_invite_exists(self, workspace_id: uuid.UUID, email: str) -> bool:
        return (
            self._db.scalars(
                select(Invitation).where(
                    Invitation.workspace_id == workspace_id,
                    Invitation.email == email,
                    Invitation.accepted_at.is_(None),
                )
            ).first()
            is not None
        )

    def create(
        self,
        workspace_id: uuid.UUID,
        email: str,
        role: WorkspaceRole,
        invited_by_user_id: uuid.UUID,
    ) -> tuple[Invitation, str]:
        """Returns (invitation, raw_token). Only the hash is persisted.

        The pending-invite pre-check below is not atomic with the INSERT
        that follows it: two concurrent invites for the same address can
        both see no pending row and race to insert. `invitations` carries a
        partial unique index on (workspace_id, email) WHERE accepted_at IS
        NULL (see migration 0004_tenancy_onboarding), so the loser of that
        race fails at INSERT time instead of silently creating a duplicate.
        That failure is caught here via a SAVEPOINT (mirroring
        TenancyService.create_workspace's slug race and auth.signup's email
        race) so only this insert rolls back -- never the surrounding
        transaction, which may hold other pending work. Racing and
        sequential callers therefore raise the identical
        ConflictError(code="invite_pending"), indistinguishable to the
        caller.
        """
        existing_user = WorkspaceRepository(self._db).get_user_by_email(email)
        if existing_user is not None:
            # WorkspaceRepository.get_membership takes (workspace_id,
            # user_id), not (user_id, workspace_id) -- verified against
            # app/repositories/workspace_repository.py. Swapping the args
            # wouldn't raise; it would silently return None forever and
            # disable this check, letting admins create duplicate
            # memberships.
            membership = WorkspaceRepository(self._db).get_membership(
                workspace_id, existing_user.id
            )
            if membership is not None:
                raise ConflictError(
                    "That person is already a member of this workspace",
                    code="already_member",
                )

        if self._pending_invite_exists(workspace_id, email):
            raise ConflictError(
                "An invitation is already pending for that address",
                code="invite_pending",
            )

        raw = generate_token()
        invitation = Invitation(
            workspace_id=workspace_id,
            email=email,
            role=role,
            token_hash=hash_token(raw),
            invited_by_user_id=invited_by_user_id,
            expires_at=datetime.now(UTC) + INVITE_TTL,
        )
        savepoint = self._db.begin_nested()
        self._db.add(invitation)
        try:
            self._db.flush()
        except IntegrityError:
            savepoint.rollback()
            raise ConflictError(
                "An invitation is already pending for that address",
                code="invite_pending",
            ) from None
        savepoint.commit()
        return invitation, raw

    def find_valid(self, raw_token: str) -> Invitation:
        invitation = self._db.scalars(
            select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
        ).first()
        if invitation is None or invitation.accepted_at is not None:
            raise InvalidTokenError("This invitation is no longer valid")
        if is_expired(invitation.expires_at):
            raise TokenExpiredError("This invitation has expired")
        return invitation

    def accept(self, invitation: Invitation, user: User) -> WorkspaceMembership:
        now = datetime.now(UTC)
        membership = WorkspaceMembership(
            workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role
        )
        self._db.add(membership)
        invitation.accepted_at = now
        # Receiving the invite at this address proves ownership of it -- an
        # invited teammate must never face a separate verification step.
        if user.email_verified_at is None:
            user.email_verified_at = now
        self._db.flush()
        return membership

    def workspace_name(self, invitation: Invitation) -> str:
        return self._db.get(Workspace, invitation.workspace_id).name
