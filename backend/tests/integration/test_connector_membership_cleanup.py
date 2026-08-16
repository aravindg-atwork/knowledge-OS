import uuid

from app.models.sync_state import ConnectorAccount, ConnectorMode, ConnectorType
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.tenancy_service import TenancyService


def _workspace_with_admin_and_member(db) -> tuple[Workspace, User, User]:
    suffix = uuid.uuid4().hex[:8]
    workspace = Workspace(name=f"Acme {suffix}", slug=f"acme-{suffix}")
    db.add(workspace)
    admin = User(email=f"admin-{suffix}@t.local", hashed_password="x")
    member = User(email=f"member-{suffix}@t.local", hashed_password="x")
    db.add(admin)
    db.add(member)
    db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=admin.id, role=WorkspaceRole.admin))
    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=member.id, role=WorkspaceRole.member))
    db.flush()
    return workspace, admin, member


def test_removing_a_member_deletes_their_connector_account(db):
    """FIX 1: a removed member's live OAuth refresh token must not survive
    the membership -- otherwise Celery beat keeps ingesting their content
    into a workspace they no longer belong to."""
    workspace, admin, member = _workspace_with_admin_and_member(db)
    account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        user_id=member.id,
        mode=ConnectorMode.real,
        display_name="Google Drive (member)",
        credential_ref={"refresh_token": "secret"},
    )
    db.add(account)
    db.flush()
    account_id = account.id

    TenancyService(db).remove_member(workspace.id, member.id)
    db.flush()

    assert db.get(ConnectorAccount, account_id) is None


def test_removing_a_member_does_not_touch_other_members_connector_accounts(db):
    workspace, admin, member = _workspace_with_admin_and_member(db)
    admin_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        user_id=admin.id,
        mode=ConnectorMode.real,
        display_name="Google Drive (admin)",
        credential_ref={"refresh_token": "secret"},
    )
    db.add(admin_account)
    db.flush()
    admin_account_id = admin_account.id

    TenancyService(db).remove_member(workspace.id, member.id)
    db.flush()

    assert db.get(ConnectorAccount, admin_account_id) is not None


def test_sync_all_connectors_task_skips_account_with_no_membership(db, monkeypatch):
    """FIX 1 (defence in depth): even if a connector account survives via
    some other path, the beat-triggered sync must not pick it up once its
    owning membership is gone."""
    from app.workers import tasks_sync

    workspace, admin, member = _workspace_with_admin_and_member(db)

    orphaned_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        user_id=member.id,
        mode=ConnectorMode.real,
        display_name="Orphaned",
        credential_ref={"refresh_token": "secret"},
    )
    live_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.gmail,
        user_id=admin.id,
        mode=ConnectorMode.real,
        display_name="Live (admin)",
        credential_ref={"refresh_token": "secret"},
    )
    shared_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        user_id=None,
        mode=ConnectorMode.mock,
        display_name="Shared/legacy",
    )
    db.add_all([orphaned_account, live_account, shared_account])
    db.flush()

    # Simulate the membership having been removed via some other path,
    # without deleting the connector account (e.g. a pre-fix removal, or a
    # future code path that this backstop is meant to guard against).
    orphan_membership = db.query(WorkspaceMembership).filter(
        WorkspaceMembership.workspace_id == workspace.id,
        WorkspaceMembership.user_id == member.id,
    ).first()
    db.delete(orphan_membership)
    db.commit()

    triggered_ids = []
    monkeypatch.setattr(
        tasks_sync.sync_connector_task, "delay", lambda account_id: triggered_ids.append(account_id)
    )

    result = tasks_sync.sync_all_connectors_task.run()

    assert str(orphaned_account.id) not in triggered_ids
    assert str(live_account.id) in triggered_ids
    assert str(shared_account.id) in triggered_ids
    assert result["triggered"] == len(triggered_ids)
