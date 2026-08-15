"""add user_id to connector_accounts (multi-account pooling per workspace)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "connector_accounts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_connector_accounts_user_id",
        "connector_accounts",
        "users",
        ["user_id"],
        ["id"],
    )
    # NULL is intentionally excluded from this constraint's enforcement
    # (Postgres unique constraints treat every NULL as distinct) -- that's
    # what lets the one shared/no-owner mock seed account keep existing
    # without a user_id, while every real per-teammate connection gets a
    # true (workspace, connector_type, user) uniqueness guarantee.
    op.create_unique_constraint(
        "uq_connector_account_owner",
        "connector_accounts",
        ["workspace_id", "connector_type", "user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_connector_account_owner", "connector_accounts", type_="unique")
    op.drop_constraint("fk_connector_accounts_user_id", "connector_accounts", type_="foreignkey")
    op.drop_column("connector_accounts", "user_id")
