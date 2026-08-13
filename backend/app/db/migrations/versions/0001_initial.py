"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "workspace_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "member", name="workspace_role"),
            nullable=False,
            server_default="member",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),
    )

    op.create_table(
        "connector_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column(
            "connector_type", sa.Enum("google_drive", name="connector_type"), nullable=False
        ),
        sa.Column(
            "mode",
            sa.Enum("mock", "real", name="connector_mode"),
            nullable=False,
            server_default="mock",
        ),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("credential_ref", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # documents.current_version_id -> document_versions.id is added as a deferred FK
    # below (after document_versions exists) to break the create-order cycle.
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column(
            "connector_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_accounts.id"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("permission_scope", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("connector_account_id", "external_id", name="uq_connector_external_id"),
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("checksum", sa.String(128), nullable=False),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extracted_title", sa.String(512), nullable=True),
        sa.Column("extracted_text_length", sa.Integer, nullable=False, server_default="0"),
        sa.Column("raw_storage_ref", sa.Text, nullable=False),
        sa.Column(
            "processing_status",
            sa.Enum(
                "pending",
                "downloading",
                "extracting",
                "chunking",
                "embedding",
                "completed",
                "failed",
                name="processing_status",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "checksum", name="uq_document_checksum"),
    )

    op.create_foreign_key(
        "fk_current_version",
        "documents",
        "document_versions",
        ["current_version_id"],
        ["id"],
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding_model", sa.String(255), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_version_id", "chunk_index", name="uq_version_chunk_index"),
    )
    op.create_index("ix_chunks_embedded_at", "chunks", ["embedded_at"])

    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "connector_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_accounts.id"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("running", "success", "failed", name="sync_run_status"),
            nullable=False,
            server_default="running",
        ),
        sa.Column("files_discovered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("files_changed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("files_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_table(
        "sync_cursors",
        sa.Column(
            "connector_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_accounts.id"),
            primary_key=True,
        ),
        sa.Column("cursor_token", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default="New chat"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id"), nullable=False
        ),
        sa.Column("role", sa.Enum("user", "assistant", name="chat_role"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "citations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "chat_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_messages.id"),
            nullable=False,
        ),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chunks.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("citations")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("sync_cursors")
    op.drop_table("sync_runs")
    op.drop_index("ix_chunks_embedded_at", table_name="chunks")
    op.drop_table("chunks")
    op.drop_constraint("fk_current_version", "documents", type_="foreignkey")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("connector_accounts")
    op.drop_table("workspace_memberships")
    op.drop_table("users")
    op.drop_table("workspaces")

    sa.Enum(name="chat_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sync_run_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="processing_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="connector_mode").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="connector_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="workspace_role").drop(op.get_bind(), checkfirst=True)
