import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, new_uuid, utcnow


class ConnectorType(str, enum.Enum):
    google_drive = "google_drive"


class ConnectorMode(str, enum.Enum):
    mock = "mock"
    real = "real"


class SyncRunStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class ConnectorAccount(Base, TimestampMixin):
    __tablename__ = "connector_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False
    )
    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(ConnectorType, name="connector_type"), nullable=False
    )
    mode: Mapped[ConnectorMode] = mapped_column(
        Enum(ConnectorMode, name="connector_mode"), nullable=False, default=ConnectorMode.mock
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


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
