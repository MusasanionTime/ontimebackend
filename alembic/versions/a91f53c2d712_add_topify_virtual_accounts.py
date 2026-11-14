"""add Topify dedicated account and webhook idempotency records

Revision ID: a91f53c2d712
Revises: c41798f4b20a
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a91f53c2d712"
down_revision: str | Sequence[str] | None = "c41798f4b20a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topify_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("request_email", sa.String(255), nullable=False),
        sa.Column("request_name", sa.String(200), nullable=False),
        sa.Column("request_phone", sa.String(30), nullable=False),
        sa.Column("customer_code", sa.String(100), nullable=True),
        sa.Column("account_number", sa.String(20), nullable=True),
        sa.Column("account_name", sa.String(200), nullable=True),
        sa.Column("bank_name", sa.String(150), nullable=True),
        sa.Column("bank_code", sa.String(20), nullable=False, server_default="30901"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("is_sandbox", sa.Boolean(), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_topify_accounts_user_id"),
        sa.UniqueConstraint("wallet_id", name="uq_topify_accounts_wallet_id"),
        sa.UniqueConstraint("customer_code", name="uq_topify_accounts_customer_code"),
    )
    op.create_index(
        "ix_topify_accounts_account_number",
        "topify_accounts",
        ["account_number"],
        unique=True,
    )
    op.create_index("ix_topify_accounts_status", "topify_accounts", ["status"])

    op.create_table(
        "topify_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.String(150), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("provider_reference", sa.String(150), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="received"),
        sa.Column("safe_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_topify_webhook_events_delivery_id",
        "topify_webhook_events",
        ["delivery_id"],
        unique=True,
    )
    op.create_index(
        "ix_topify_webhook_events_event_type", "topify_webhook_events", ["event_type"]
    )
    op.create_index(
        "ix_topify_webhook_events_provider_reference",
        "topify_webhook_events",
        ["provider_reference"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_topify_webhook_events_provider_reference",
        table_name="topify_webhook_events",
    )
    op.drop_index(
        "ix_topify_webhook_events_event_type", table_name="topify_webhook_events"
    )
    op.drop_index(
        "ix_topify_webhook_events_delivery_id", table_name="topify_webhook_events"
    )
    op.drop_table("topify_webhook_events")
    op.drop_index("ix_topify_accounts_status", table_name="topify_accounts")
    op.drop_index("ix_topify_accounts_account_number", table_name="topify_accounts")
    op.drop_table("topify_accounts")
