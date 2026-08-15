import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_FALLBACK_SLUG = "workspace"
_MAX_WORKSPACE_NAME = 100


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
        name = validate_workspace_name(name)
        workspace = Workspace(name=name, slug=self.generate_slug(name))
        self._db.add(workspace)
        self._db.flush()
        self._db.add(
            WorkspaceMembership(
                workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.admin
            )
        )
        self._db.flush()
        return workspace

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
