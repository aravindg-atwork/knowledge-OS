import re
import uuid

import pytest
from sqlalchemy import select

from app.core.rate_limit import limiter
from app.db.base import utcnow
from app.models.document import Document
from app.models.sync_state import (
    ConnectorAccount,
    ConnectorMode,
    ConnectorType,
    SyncCursor,
    SyncRun,
    SyncRunStatus,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.tenancy_service import TenancyService


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate limits are Redis-backed and keyed by client IP, which TestClient
    always reports as the same address. Without a reset, calls across this
    file's tests trip the limiter and return 429 instead of the status under
    test."""
    limiter.reset()
    yield


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


def test_removing_a_member_soft_disables_their_connector_account(db):
    """FIX 2 (soft-disable, not delete): a removed member's live OAuth
    refresh token must not survive the membership -- but the account row
    itself, and anything it already ingested, must stay. Deleting the row
    (the original fix) raises a FOREIGN KEY violation for any account that
    ever actually synced something -- see the dependent-graph test below."""
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

    reloaded = db.get(ConnectorAccount, account_id)
    assert reloaded is not None
    assert reloaded.disabled_at is not None
    assert reloaded.credential_ref == {}


def test_removing_a_member_with_documents_and_sync_history_keeps_the_knowledge_base(db):
    """The regression this guards against: a member who actually synced has
    ConnectorAccount rows referenced (with no ondelete rule) by documents,
    sync_runs, and sync_cursors. The original fix's bulk delete() of
    ConnectorAccount hit a FOREIGN KEY violation here -> unhandled
    IntegrityError -> 500, and the membership wasn't even removed.

    The product decision: soft-disable. Remove the member cleanly, sever
    their Google access, but keep every document already ingested -- that
    content is already shared with, and relied on by, the whole workspace.
    """
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

    document = Document(
        workspace_id=workspace.id,
        connector_account_id=account.id,
        external_id="ext-1",
        title="Q3 roadmap",
        mime_type="text/plain",
        source_url="https://example.com/doc/ext-1",
    )
    db.add(document)

    sync_run = SyncRun(
        connector_account_id=account.id,
        started_at=utcnow(),
        status=SyncRunStatus.success,
        files_discovered=1,
        files_changed=1,
    )
    db.add(sync_run)

    sync_cursor = SyncCursor(connector_account_id=account.id, cursor_token="cursor-1")
    db.add(sync_cursor)
    db.flush()
    document_id = document.id

    # This must not raise (the regression: FOREIGN KEY violation ->
    # unhandled IntegrityError -> 500).
    TenancyService(db).remove_member(workspace.id, member.id)
    db.flush()

    membership = db.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == member.id,
        )
    ).first()
    assert membership is None

    reloaded_account = db.get(ConnectorAccount, account_id)
    assert reloaded_account is not None
    assert reloaded_account.disabled_at is not None
    assert reloaded_account.credential_ref == {}

    # The workspace keeps its knowledge base.
    reloaded_document = db.get(Document, document_id)
    assert reloaded_document is not None
    assert reloaded_document.is_deleted is False


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

    reloaded = db.get(ConnectorAccount, admin_account_id)
    assert reloaded is not None
    assert reloaded.disabled_at is None
    assert reloaded.credential_ref == {"refresh_token": "secret"}


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


def test_sync_all_connectors_task_skips_disabled_account(db, monkeypatch):
    """FIX 2: the scheduler must not pick up an account soft-disabled by
    remove_member, even though its membership-based backstop wouldn't catch
    it on its own if some other membership happened to exist for that
    (workspace_id, user_id) pair."""
    from app.workers import tasks_sync

    workspace, admin, member = _workspace_with_admin_and_member(db)

    disabled_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        user_id=member.id,
        mode=ConnectorMode.real,
        display_name="Disabled (member)",
        credential_ref={},
        disabled_at=utcnow(),
    )
    live_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.gmail,
        user_id=admin.id,
        mode=ConnectorMode.real,
        display_name="Live (admin)",
        credential_ref={"refresh_token": "secret"},
    )
    db.add_all([disabled_account, live_account])
    db.commit()

    triggered_ids = []
    monkeypatch.setattr(
        tasks_sync.sync_connector_task, "delay", lambda account_id: triggered_ids.append(account_id)
    )

    result = tasks_sync.sync_all_connectors_task.run()

    assert str(disabled_account.id) not in triggered_ids
    assert str(live_account.id) in triggered_ids
    assert result["triggered"] == len(triggered_ids)


def test_sync_all_connectors_task_still_syncs_shared_account_with_no_user(db, monkeypatch):
    """Guard against re-breaking the earlier fix: user_id IS NULL
    shared/legacy accounts (e.g. the mock seed connector) have no owning
    membership to check and must always sync, so long as they're not
    disabled."""
    from app.workers import tasks_sync

    workspace, admin, member = _workspace_with_admin_and_member(db)

    shared_account = ConnectorAccount(
        workspace_id=workspace.id,
        connector_type=ConnectorType.google_drive,
        user_id=None,
        mode=ConnectorMode.mock,
        display_name="Shared/legacy",
    )
    db.add(shared_account)
    db.commit()

    triggered_ids = []
    monkeypatch.setattr(
        tasks_sync.sync_connector_task, "delay", lambda account_id: triggered_ids.append(account_id)
    )

    result = tasks_sync.sync_all_connectors_task.run()

    assert str(shared_account.id) in triggered_ids
    assert result["triggered"] == len(triggered_ids)


# --- Manual /sync endpoint --------------------------------------------------


@pytest.fixture
def fake_email(client):
    """Override on the app instance `client` wraps. tests/conftest.py builds a
    fresh app per test via create_app(), so overriding app.main's module-level
    singleton would silently miss this client's requests."""
    from app.email.factory import get_email_provider
    from app.email.provider import FakeEmailProvider

    provider = FakeEmailProvider()
    client.app.dependency_overrides[get_email_provider] = lambda: provider
    yield provider
    client.app.dependency_overrides.pop(get_email_provider, None)


def _verified_admin(client, fake_email) -> tuple[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@acme.com"
    token = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "pw-pw-pw-pw", "full_name": "A", "workspace_name": "Acme"},
    ).json()["access_token"]
    raw = re.search(r"token=([A-Za-z0-9_\-]+)", fake_email.sent[-1].text).group(1)
    client.post("/api/v1/auth/verify-email", json={"token": raw})
    return token, email


def test_manual_sync_refuses_a_disabled_connector_account(client, fake_email, db):
    """FIX 3: a disabled account must not be re-triggerable by hand through
    the manual "sync now" endpoint, and must fail the same way an
    never-connected account does (NotFoundError), not with a new error
    shape."""
    token, email = _verified_admin(client, fake_email)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers).json()

    account = ConnectorAccount(
        workspace_id=uuid.UUID(me["active_workspace_id"]),
        connector_type=ConnectorType.google_drive,
        user_id=uuid.UUID(me["user_id"]),
        mode=ConnectorMode.real,
        display_name="Google Drive (admin)",
        credential_ref={},
        disabled_at=utcnow(),
    )
    db.add(account)
    db.commit()

    resp = client.post("/api/v1/connectors/google-drive/sync", headers=headers)

    assert resp.status_code == 404
