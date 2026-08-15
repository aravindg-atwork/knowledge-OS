import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FALLBACK_SLUG = "workspace"
_MAX_WORKSPACE_NAME = 100
_MAX_SLUG_ATTEMPTS = 5


def validate_workspace_name(name: str) -> str:
    """Single definition of what a workspace name may be, used by signup,
    workspace creation, and rename.

    Workspace names are set by whoever signs up and are rendered into
    invitation emails that land in other people's inboxes. The templates
    escape on output -- that is the real defense -- but rejecting angle
    brackets at the door keeps the worst inputs out of the database in the
    first place.
    """
    cleaned = name.strip()
    if not 1 <= len(cleaned) <= _MAX_WORKSPACE_NAME:
        raise ConflictError(
            f"Workspace name must be 1-{_MAX_WORKSPACE_NAME} characters",
            code="invalid_workspace_name",
        )
    if "<" in cleaned or ">" in cleaned:
        raise ConflictError(
            "Workspace name may not contain < or >", code="invalid_workspace_name"
        )
    # Control characters -- newlines especially -- must not survive. The
    # workspace name is interpolated into the *subject* of invitation email,
    # and a newline there is header injection (an attacker-added Bcc, say).
    # .strip() only removes surrounding whitespace, so an interior "\n" would
    # otherwise pass straight through to the mail transport.
    if any(ch < " " or ch == "\x7f" for ch in cleaned):
        raise ConflictError(
            "Workspace name may not contain control characters",
            code="invalid_workspace_name",
        )
    return cleaned


class TenancyService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def generate_slug(self, name: str) -> str:
        base = _SLUG_STRIP.sub("-", name.lower()).strip("-") or _FALLBACK_SLUG
        candidate = base
        suffix = 1
        while self._slug_taken(candidate):
            suffix += 1
            candidate = f"{base}-{suffix}"
        return candidate

    def _slug_taken(self, slug: str) -> bool:
        return (
            self._db.scalars(select(Workspace).where(Workspace.slug == slug)).first() is not None
        )

    def create_workspace(self, name: str, owner: User) -> Workspace:
        """Create a workspace with a unique slug and make ``owner`` an admin.

        ``generate_slug``'s SELECT-then-decide check is not atomic with the
        INSERT here: two concurrent signups for the same company name can
        both see the same free slug and race to insert it. The DB's unique
        constraint on ``Workspace.slug`` is the real guard; this loop just
        makes sure the loser of that race gets a clean retry (and eventually
        a clean AppError) instead of an unhandled IntegrityError bubbling up
        as a 500. Each attempt runs inside a SAVEPOINT so a failed attempt
        rolls back only its own insert -- not the surrounding transaction,
        which may already hold other pending work (e.g. signup's User and
        AuthToken inserts).
        """
        name = validate_workspace_name(name)
        last_error: IntegrityError | None = None
        for _ in range(_MAX_SLUG_ATTEMPTS):
            slug = self.generate_slug(name)
            savepoint = self._db.begin_nested()
            workspace = Workspace(name=name, slug=slug)
            self._db.add(workspace)
            try:
                self._db.flush()
            except IntegrityError as exc:
                savepoint.rollback()
                last_error = exc
                continue
            savepoint.commit()

            # Only insert the membership once the workspace insert has
            # actually succeeded, so a retried attempt never leaves an
            # orphaned admin membership behind.
            self._db.add(
                WorkspaceMembership(
                    workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.admin
                )
            )
            self._db.flush()
            return workspace

        raise ConflictError(
            "Could not allocate a unique workspace slug",
            code="slug_allocation_failed",
        ) from last_error

    def list_memberships(self, user_id: uuid.UUID) -> list[WorkspaceMembership]:
        return list(
            self._db.scalars(
                select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
            )
        )

    def count_admins(self, workspace_id: uuid.UUID) -> int:
        return self._db.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == WorkspaceRole.admin,
            )
        )

    def change_role(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID, role: WorkspaceRole
    ) -> WorkspaceMembership:
        membership = self._get_membership_or_raise(workspace_id, user_id)
        if membership.role is WorkspaceRole.admin and role is WorkspaceRole.member:
            # See _lock_admin_memberships: without this row lock, two
            # concurrent demotions of two different admins can both read
            # count == 2, both pass the guard, and both commit, leaving the
            # workspace with zero admins -- an unrecoverable state via the
            # API. Do not replace this with count_admins(); that's a plain
            # (unlocked) SELECT and reintroduces the race.
            if len(self._lock_admin_memberships(workspace_id)) <= 1:
                raise ConflictError(
                    "A workspace must keep at least one admin", code="last_admin"
                )
        membership.role = role
        self._db.flush()
        return membership

    def remove_member(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> None:
        membership = self._get_membership_or_raise(workspace_id, user_id)
        if membership.role is WorkspaceRole.admin:
            # Same TOCTOU concern as change_role: lock the admin rows before
            # counting so a concurrent remove/demote of another admin can't
            # race this check and leave the workspace admin-less.
            if len(self._lock_admin_memberships(workspace_id)) <= 1:
                raise ConflictError(
                    "A workspace must keep at least one admin", code="last_admin"
                )
        self._db.delete(membership)
        self._db.flush()

    def _lock_admin_memberships(self, workspace_id: uuid.UUID) -> list[WorkspaceMembership]:
        """SELECT ... FOR UPDATE on the workspace's admin membership rows.

        This makes the last-admin guard atomic with the mutation that
        follows it: a second concurrent transaction trying to demote/remove
        a *different* admin in the same workspace blocks here until the
        first transaction commits (or rolls back), then re-reads the row
        set and correctly observes the reduced admin count. Without this
        lock, two concurrent demotions/removals of two different admins can
        both read count() == 2, both pass the guard, and both commit --
        leaving a workspace with zero admins, which nothing in the API can
        ever repair (no admin left to invite, remove, or promote anyone).
        Postgres rejects FOR UPDATE combined with an aggregate, so this
        locks and materializes the rows and callers take len() themselves
        rather than locking a count(*) query directly.
        """
        return list(
            self._db.scalars(
                select(WorkspaceMembership)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.role == WorkspaceRole.admin,
                )
                .with_for_update()
            )
        )

    def _get_membership_or_raise(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceMembership:
        membership = self._db.scalars(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        ).first()
        if membership is None:
            raise NotFoundError("That person is not a member of this workspace")
        return membership
