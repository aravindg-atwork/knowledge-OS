"""tenancy: auth tokens, invitations, user verification fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Backfill existing rows. email_verified_at is nullable and new signups
    # start out NULL (unverified) on purpose -- but every user who predates
    # this migration was created before email verification existed at all.
    # Leaving their column NULL would retroactively brand them "unverified"
    # and get_current_user (app/api/deps.py) would start raising
    # EmailNotVerifiedError on documents/chat/connectors for every one of
    # them the moment this migration runs, with no way for them to
    # self-serve a fix (they have no pending verification email). Stamping
    # now() treats "already had an account before verification was a
    # concept" as equivalent to "verified".
    op.execute("UPDATE users SET email_verified_at = now() WHERE email_verified_at IS NULL")

    auth_token_purpose = postgresql.ENUM(
        "verify_email", "password_reset", name="auth_token_purpose"
    )
    auth_token_purpose.create(op.get_bind(), checkfirst=True)
    # The type now exists; reference it without create_type so create_table
    # below doesn't attempt (and fail) to CREATE TYPE a second time.
    auth_token_purpose_ref = postgresql.ENUM(
        "verify_email", "password_reset", name="auth_token_purpose", create_type=False
    )

    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", auth_token_purpose_ref, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])
    op.create_index("ix_auth_tokens_token_hash", "auth_tokens", ["token_hash"])

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM("admin", "member", name="workspace_role", create_type=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invitations_workspace_id", "invitations", ["workspace_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])
    op.create_index("ix_invitations_token_hash", "invitations", ["token_hash"])
    # Partial: no duplicate *pending* invites, but re-inviting someone who
    # left is allowed.
    op.create_index(
        "uq_invitations_pending_workspace_email",
        "invitations",
        ["workspace_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_table("auth_tokens")
    postgresql.ENUM(name="auth_token_purpose").drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "full_name")
