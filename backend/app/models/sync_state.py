import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid, utcnow


class ConnectorType(str, enum.Enum):
    google_drive = "google_drive"
    gmail = "gmail"


class ConnectorMode(str, enum.Enum):
    mock = "mock"
    real = "real"


class SyncRunStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class ConnectorAccount(Base, TimestampMixin):
    """One connected source-account. Multiple teammates in the same
    workspace can each have their own row of the same connector_type (e.g.
    Alice's Gmail and Bob's Gmail both connected) -- everything they connect
    pools into the same workspace-scoped, role-gated document/chat corpus;
    nothing about retrieval is keyed off which account ingested a document.

    user_id is nullable to allow the one shared/workspace-level mock seed
    account (no individual owner) to keep working unchanged; every "real"
    (OAuth-connected) account always has user_id set to whoever connected it.
    """

    __tablename__ = "connector_accounts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "connector_type", "user_id", name="uq_connector_account_owner"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(ConnectorType, name="connector_type"), nullable=False
    )
    mode: Mapped[ConnectorMode] = mapped_column(
        Enum(ConnectorMode, name="connector_mode"), nullable=False, default=ConnectorMode.mock
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Set when the connecting member is removed from the workspace (see
    # TenancyService.remove_member). The account and everything it already
    # ingested are kept -- that content is already part of the workspace's
    # shared corpus -- but disabled_at marks it as no longer live: the
    # scheduler (sync_all_connectors_task) and the manual /sync endpoint both
    # skip it. credential_ref is cleared out alongside this (not modeled
    # here, done at the call site) since that's what actually revokes the
    # stored Google refresh token.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    connector_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_accounts.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[SyncRunStatus] = mapped_column(
        Enum(SyncRunStatus, name="sync_run_status"),
        nullable=False,
        default=SyncRunStatus.running,
    )
    files_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class SyncCursor(Base):
    __tablename__ = "sync_cursors"

    connector_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connector_accounts.id"), primary_key=True
    )
    cursor_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
