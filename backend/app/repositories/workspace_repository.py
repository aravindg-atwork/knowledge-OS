import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership


class WorkspaceRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_workspace(self, workspace_id: uuid.UUID) -> Workspace | None:
        return self._db.get(Workspace, workspace_id)

    def get_membership(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceMembership | None:
        stmt = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        return self._db.scalars(stmt).first()

    def get_user_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self._db.scalars(stmt).first()
