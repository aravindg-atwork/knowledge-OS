from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.sync_state import ConnectorAccount, ConnectorMode, ConnectorType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

DEFAULT_WORKSPACE_SLUG = "acme"
DEFAULT_USER_EMAIL = "demo@acme-corp.com"
DEFAULT_USER_PASSWORD = "password123"


def seed_dev_data() -> dict:
    """Idempotent: creates a default workspace/user/mock-connector-account
    for local dev if they don't already exist, and returns their ids."""
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.slug == DEFAULT_WORKSPACE_SLUG).first()
        if workspace is None:
            workspace = Workspace(name="Acme Corp", slug=DEFAULT_WORKSPACE_SLUG)
            db.add(workspace)
            db.flush()

        user = db.query(User).filter(User.email == DEFAULT_USER_EMAIL).first()
        if user is None:
            user = User(
                email=DEFAULT_USER_EMAIL,
                hashed_password=hash_password(DEFAULT_USER_PASSWORD),
            )
            db.add(user)
            db.flush()

        membership = (
            db.query(WorkspaceMembership)
            .filter(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == user.id,
            )
            .first()
        )
        if membership is None:
            db.add(
                WorkspaceMembership(
                    workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.admin
                )
            )

        connector_account = (
            db.query(ConnectorAccount)
            .filter(
                ConnectorAccount.workspace_id == workspace.id,
                ConnectorAccount.connector_type == ConnectorType.google_drive,
            )
            .first()
        )
        if connector_account is None:
            connector_account = ConnectorAccount(
                workspace_id=workspace.id,
                connector_type=ConnectorType.google_drive,
                mode=ConnectorMode.mock,
                display_name="Google Drive (Mock)",
            )
            db.add(connector_account)
            db.flush()

        db.commit()
        return {
            "workspace_id": str(workspace.id),
            "user_id": str(user.id),
            "user_email": user.email,
            "user_password": DEFAULT_USER_PASSWORD,
            "connector_account_id": str(connector_account.id),
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(seed_dev_data())
