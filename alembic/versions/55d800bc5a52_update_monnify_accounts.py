"""update monnify accounts

Revision ID: 55d800bc5a52
Revises: 12e1ebee3811
Create Date: 2026-08-18 14:33:40.831878
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "55d800bc5a52"
down_revision: Union[str, Sequence[str], None] = "12e1ebee3811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.add_column(
        "monnify_accounts",
        sa.Column(
            "wallet_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    op.add_column(
        "monnify_accounts",
        sa.Column(
            "reservation_reference",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.add_column(
        "monnify_accounts",
        sa.Column(
            "currency",
            sa.String(length=10),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_monnify_accounts_reservation_reference",
        "monnify_accounts",
        ["reservation_reference"],
        unique=True,
    )

    op.create_index(
        "ix_monnify_accounts_wallet_id",
        "monnify_accounts",
        ["wallet_id"],
        unique=True,
    )

    op.create_foreign_key(
        "fk_monnify_accounts_wallet_id",
        "monnify_accounts",
        "wallets",
        ["wallet_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_constraint(
        "fk_monnify_accounts_wallet_id",
        "monnify_accounts",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_monnify_accounts_wallet_id",
        table_name="monnify_accounts",
    )

    op.drop_index(
        "ix_monnify_accounts_reservation_reference",
        table_name="monnify_accounts",
    )

    op.drop_column(
        "monnify_accounts",
        "currency",
    )

    op.drop_column(
        "monnify_accounts",
        "reservation_reference",
    )

    op.drop_column(
        "monnify_accounts",
        "wallet_id",
    )