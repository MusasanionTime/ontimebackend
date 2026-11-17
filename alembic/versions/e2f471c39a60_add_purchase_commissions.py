"""add disabled-by-default purchase commission accounting

Revision ID: e2f471c39a60
Revises: a91f53c2d712
"""

from collections.abc import Sequence
from datetime import datetime, timezone
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "e2f471c39a60"
down_revision: str | Sequence[str] | None = "a91f53c2d712"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commission_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_key", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("calculation_type", sa.String(length=20), nullable=True),
        sa.Column("commission_value", sa.Numeric(20, 6), nullable=True),
        sa.Column("calculation_basis", sa.String(length=30), nullable=True),
        sa.Column("minimum_commission", sa.Numeric(20, 2), nullable=True),
        sa.Column("maximum_commission", sa.Numeric(20, 2), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("commission_value IS NULL OR commission_value > 0", name="ck_commission_config_value_positive"),
        sa.CheckConstraint("minimum_commission IS NULL OR minimum_commission >= 0", name="ck_commission_config_min_nonnegative"),
        sa.CheckConstraint("maximum_commission IS NULL OR maximum_commission >= 0", name="ck_commission_config_max_nonnegative"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_key", "revision", name="uq_commission_config_service_revision"),
    )
    op.create_index("ix_commission_configurations_service_key", "commission_configurations", ["service_key"])
    op.create_index("ix_commission_configurations_effective_from", "commission_configurations", ["effective_from"])
    op.create_index("ix_commission_configurations_created_by_admin_id", "commission_configurations", ["created_by_admin_id"])

    op.create_table(
        "purchase_commissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("source_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("platform_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("service_category", sa.String(length=40), nullable=False),
        sa.Column("purchase_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("calculation_type", sa.String(length=20), nullable=False),
        sa.Column("calculation_value", sa.Numeric(20, 6), nullable=False),
        sa.Column("calculation_basis", sa.String(length=30), nullable=False),
        sa.Column("commission_amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="posted"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("purchase_amount > 0", name="ck_purchase_commission_purchase_positive"),
        sa.CheckConstraint("commission_amount > 0", name="ck_purchase_commission_amount_positive"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["configuration_id"], ["commission_configurations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_transaction_id"], ["platform_transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference", name="uq_purchase_commissions_reference"),
        sa.UniqueConstraint("source_transaction_id", name="uq_purchase_commissions_source_transaction"),
        sa.UniqueConstraint("platform_transaction_id", name="uq_purchase_commissions_platform_transaction"),
    )
    op.create_index("ix_purchase_commissions_reference", "purchase_commissions", ["reference"])
    op.create_index("ix_purchase_commissions_customer_id", "purchase_commissions", ["customer_id"])
    op.create_index("ix_purchase_commissions_source_transaction_id", "purchase_commissions", ["source_transaction_id"])
    op.create_index("ix_purchase_commissions_configuration_id", "purchase_commissions", ["configuration_id"])
    op.create_index("ix_purchase_commissions_service_category", "purchase_commissions", ["service_category"])
    op.create_index("ix_purchase_commissions_status", "purchase_commissions", ["status"])
    op.create_index("ix_purchase_commissions_created_at", "purchase_commissions", ["created_at"])

    op.create_table(
        "commission_reversals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("commission_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column("refund_reference", sa.String(length=100), nullable=False),
        sa.Column("platform_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(20, 2), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_review"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_commission_reversal_amount_positive"),
        sa.ForeignKeyConstraint(["commission_id"], ["purchase_commissions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_transaction_id"], ["platform_transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("commission_id", name="uq_commission_reversals_commission"),
        sa.UniqueConstraint("reference", name="uq_commission_reversals_reference"),
        sa.UniqueConstraint("platform_transaction_id", name="uq_commission_reversals_platform_transaction"),
    )
    op.create_index("ix_commission_reversals_commission_id", "commission_reversals", ["commission_id"])
    op.create_index("ix_commission_reversals_reference", "commission_reversals", ["reference"])
    op.create_index("ix_commission_reversals_refund_reference", "commission_reversals", ["refund_reference"])
    op.create_index("ix_commission_reversals_status", "commission_reversals", ["status"])
    op.create_index("ix_commission_reversals_created_by_admin_id", "commission_reversals", ["created_by_admin_id"])
    op.create_index("ix_commission_reversals_created_at", "commission_reversals", ["created_at"])

    op.bulk_insert(
        sa.table(
            "commission_configurations",
            sa.column("id", sa.Uuid()),
            sa.column("service_key", sa.String()),
            sa.column("revision", sa.Integer()),
            sa.column("is_enabled", sa.Boolean()),
            sa.column("effective_from", sa.DateTime(timezone=True)),
            sa.column("reason", sa.Text()),
        ),
        [{
            "id": uuid.uuid4(),
            "service_key": "global",
            "revision": 1,
            "is_enabled": False,
            "effective_from": datetime.now(timezone.utc),
            "reason": "Initial system default; commission processing disabled pending owner approval.",
        }],
    )


def downgrade() -> None:
    op.drop_index("ix_commission_reversals_created_at", table_name="commission_reversals")
    op.drop_index("ix_commission_reversals_created_by_admin_id", table_name="commission_reversals")
    op.drop_index("ix_commission_reversals_status", table_name="commission_reversals")
    op.drop_index("ix_commission_reversals_refund_reference", table_name="commission_reversals")
    op.drop_index("ix_commission_reversals_reference", table_name="commission_reversals")
    op.drop_index("ix_commission_reversals_commission_id", table_name="commission_reversals")
    op.drop_table("commission_reversals")

    op.drop_index("ix_purchase_commissions_created_at", table_name="purchase_commissions")
    op.drop_index("ix_purchase_commissions_status", table_name="purchase_commissions")
    op.drop_index("ix_purchase_commissions_service_category", table_name="purchase_commissions")
    op.drop_index("ix_purchase_commissions_configuration_id", table_name="purchase_commissions")
    op.drop_index("ix_purchase_commissions_source_transaction_id", table_name="purchase_commissions")
    op.drop_index("ix_purchase_commissions_customer_id", table_name="purchase_commissions")
    op.drop_index("ix_purchase_commissions_reference", table_name="purchase_commissions")
    op.drop_table("purchase_commissions")

    op.drop_index("ix_commission_configurations_created_by_admin_id", table_name="commission_configurations")
    op.drop_index("ix_commission_configurations_effective_from", table_name="commission_configurations")
    op.drop_index("ix_commission_configurations_service_key", table_name="commission_configurations")
    op.drop_table("commission_configurations")
