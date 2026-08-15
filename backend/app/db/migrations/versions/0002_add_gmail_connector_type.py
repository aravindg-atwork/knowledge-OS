"""add gmail connector type

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres allows adding an enum value inside a transaction (PG12+) as
    # long as it isn't *used* in that same transaction, which we don't do
    # here -- just registering it.
    op.execute("ALTER TYPE connector_type ADD VALUE IF NOT EXISTS 'gmail'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Downgrading would require
    # rebuilding the enum (rename -> create old-shape type -> cast column
    # over -> drop renamed type), which is only safe if no connector_accounts
    # row already uses 'gmail'. Left unimplemented, matching this repo's
    # other additive-only migrations; delete any gmail rows by hand first if
    # you truly need to downgrade past this revision.
    raise NotImplementedError("Downgrading past 0002 (drop 'gmail' enum value) is not supported")
