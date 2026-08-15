import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.api.deps import invalidate_membership_cache
from app.core.security import create_access_token
from app.models.user import User
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.tenancy_service import TenancyService


def _membership(db, user_id, workspace_id) -> WorkspaceMembership:
    return db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    ).first()


def _verified_user(db, role=WorkspaceRole.admin):
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@t.local",
        hashed_password="x",
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    workspace = TenancyService(db).create_workspace(f"Acme {uuid.uuid4().hex[:8]}", user)
    if role is WorkspaceRole.member:
        _membership(db, user.id, workspace.id).role = WorkspaceRole.member
    db.commit()
    return user, workspace


def test_valid_member_is_accepted(client, db):
    user, workspace = _verified_user(db)
    token = create_access_token(user.id, workspace.id)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_removed_member_loses_access(client, db):
    user, workspace = _verified_user(db)
    token = create_access_token(user.id, workspace.id)
    assert client.get(
        "/api/v1/documents", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200

    db.delete(_membership(db, user.id, workspace.id))
    db.commit()
    invalidate_membership_cache(user.id, workspace.id)

    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_token_for_a_workspace_you_never_joined_is_rejected(client, db):
    user, _ = _verified_user(db)
    other_workspace_id = uuid.uuid4()
    token = create_access_token(user.id, other_workspace_id)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_inactive_user_is_rejected(client, db):
    user, workspace = _verified_user(db)
    token = create_access_token(user.id, workspace.id)
    user.is_active = False
    db.commit()
    invalidate_membership_cache(user.id, workspace.id)
    resp = client.get("/api/v1/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_member_cannot_start_connector_oauth(client, db):
    user, workspace = _verified_user(db, role=WorkspaceRole.member)
    invalidate_membership_cache(user.id, workspace.id)
    token = create_access_token(user.id, workspace.id)
    resp = client.get(
        "/api/v1/connectors/google/oauth/start?connector_type=google_drive",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "admin_required"


def test_member_can_still_sync_their_own_connector(client, db):
    """Syncing your own connection is a member action -- only connecting and
    disconnecting are admin-gated."""
    user, workspace = _verified_user(db, role=WorkspaceRole.member)
    invalidate_membership_cache(user.id, workspace.id)
    token = create_access_token(user.id, workspace.id)
    resp = client.post(
        "/api/v1/connectors/google-drive/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 (no connection of their own yet), never 403.
    assert resp.status_code != 403
