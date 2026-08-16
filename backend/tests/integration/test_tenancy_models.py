import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.auth_token import AuthToken, AuthTokenPurpose
from app.models.invitation import Invitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceRole


def _workspace(db) -> Workspace:
    ws = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    db.flush()
    return ws


def test_user_defaults_to_unverified(db):
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(user)
    db.flush()
    assert user.email_verified_at is None
    assert user.full_name is None


def test_auth_token_roundtrips(db):
    user = User(email=f"u-{uuid.uuid4().hex[:8]}@t.local", hashed_password="x")
    db.add(user)
    db.flush()
    token = AuthToken(
        user_id=user.id,
        purpose=AuthTokenPurpose.verify_email,
        token_hash="deadbeef",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(token)
    db.flush()
    assert token.used_at is None


def test_pending_invite_is_unique_per_workspace_and_email(db):
    ws = _workspace(db)
    for _ in range(2):
        db.add(
            Invitation(
                workspace_id=ws.id,
                email="dup@acme.com",
                role=WorkspaceRole.member,
                token_hash=uuid.uuid4().hex,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_accepted_invite_does_not_block_reinvite(db):
    ws = _workspace(db)
    db.add(
        Invitation(
            workspace_id=ws.id,
            email="returning@acme.com",
            role=WorkspaceRole.member,
            token_hash=uuid.uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=7),
            accepted_at=datetime.now(UTC),
        )
    )
    db.flush()
    db.add(
        Invitation(
            workspace_id=ws.id,
            email="returning@acme.com",
            role=WorkspaceRole.member,
            token_hash=uuid.uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    db.flush()  # must not raise -- the unique index is partial
