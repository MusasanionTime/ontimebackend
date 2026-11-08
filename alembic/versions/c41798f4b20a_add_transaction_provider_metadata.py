"""store Monnify invoice details for deposit history and reconciliation

Revision ID: c41798f4b20a
Revises: 8b2d1e9c4a10
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c41798f4b20a"
down_revision: Union[str, Sequence[str], None] = "8b2d1e9c4a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("provider_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "provider_metadata")
