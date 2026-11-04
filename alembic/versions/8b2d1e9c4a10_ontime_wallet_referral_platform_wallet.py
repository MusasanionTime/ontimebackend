"""ONTIME wallet numbers, referrals and platform wallet

Revision ID: 8b2d1e9c4a10
Revises: 24a8373fa340
"""

from typing import Sequence, Union
import secrets
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8b2d1e9c4a10"
down_revision: Union[str, Sequence[str], None] = "24a8373fa340"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_wallet_number(existing: set[str]) -> str:
    """
    Generate a unique ONTIME wallet number.

    Format:
        82XXXXXXXX
    Example:
        8212345678
    """
    while True:
        value = f"82{secrets.randbelow(100_000_000):08d}"

        if value not in existing:
            existing.add(value)
            return value


def _unique_referral_code(existing: set[str]) -> str:
    """
    Generate a unique ONTIME referral code.

    Example:
        ONTAB7K92
    """

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    while True:
        value = "ONT" + "".join(
            secrets.choice(alphabet)
            for _ in range(7)
        )

        if value not in existing:
            existing.add(value)
            return value


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:

    # ============================================================
    # 1. USER REFERRAL FIELDS
    # ============================================================

    op.add_column(
        "users",
        sa.Column(
            "referral_code",
            sa.String(length=30),
            nullable=True,
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "referred_by_id",
            sa.Uuid(),
            nullable=True,
        ),
    )

    # ============================================================
    # 2. WALLET NUMBER
    # ============================================================

    op.add_column(
        "wallets",
        sa.Column(
            "wallet_number",
            sa.String(length=30),
            nullable=True,
        ),
    )

    bind = op.get_bind()

    # ============================================================
    # 3. BACKFILL REFERRAL CODES
    # ============================================================

    existing_codes = {
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT referral_code
                FROM users
                WHERE referral_code IS NOT NULL
                """
            )
        )
    }

    user_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id
                FROM users
                WHERE referral_code IS NULL
                """
            )
        )
    )

    for row in user_rows:

        referral_code = _unique_referral_code(
            existing_codes
        )

        bind.execute(
            sa.text(
                """
                UPDATE users
                SET referral_code = :code
                WHERE id = :id
                """
            ),
            {
                "code": referral_code,
                "id": row.id,
            },
        )

    # ============================================================
    # 4. BACKFILL WALLET NUMBERS
    # ============================================================

    existing_wallet_numbers = {
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT wallet_number
                FROM wallets
                WHERE wallet_number IS NOT NULL
                """
            )
        )
    }

    wallet_rows = list(
        bind.execute(
            sa.text(
                """
                SELECT id
                FROM wallets
                WHERE wallet_number IS NULL
                """
            )
        )
    )

    for row in wallet_rows:

        wallet_number = _unique_wallet_number(
            existing_wallet_numbers
        )

        bind.execute(
            sa.text(
                """
                UPDATE wallets
                SET wallet_number = :number
                WHERE id = :id
                """
            ),
            {
                "number": wallet_number,
                "id": row.id,
            },
        )

    # ============================================================
    # 5. USER REFERRAL INDEXES
    # ============================================================

    op.create_index(
        "ix_users_referral_code",
        "users",
        ["referral_code"],
        unique=True,
    )

    op.create_index(
        "ix_users_referred_by_id",
        "users",
        ["referred_by_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_users_referred_by_id",
        "users",
        "users",
        ["referred_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # ============================================================
    # 6. WALLET NUMBER INDEX
    # ============================================================

    op.create_index(
        "ix_wallets_wallet_number",
        "wallets",
        ["wallet_number"],
        unique=True,
    )

    # Existing users must have referral codes.
    op.alter_column(
        "users",
        "referral_code",
        existing_type=sa.String(length=30),
        nullable=False,
    )

    # Existing wallets must have wallet numbers.
    op.alter_column(
        "wallets",
        "wallet_number",
        existing_type=sa.String(length=30),
        nullable=False,
    )

    # ============================================================
    # 7. REFERRAL SETTINGS
    # ============================================================

    op.create_table(
        "referral_settings",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),

        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),

        sa.Column(
            "reward_type",
            sa.String(length=20),
            nullable=False,
            server_default="fixed",
        ),

        sa.Column(
            "reward_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="0",
        ),

        sa.Column(
            "min_qualifying_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="0",
        ),

        sa.Column(
            "reward_on_first_transaction",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Default referral configuration.
    op.execute(
        sa.text(
            """
            INSERT INTO referral_settings
            (
                id,
                is_enabled,
                reward_type,
                reward_amount,
                min_qualifying_amount,
                reward_on_first_transaction
            )
            VALUES
            (
                1,
                false,
                'fixed',
                0,
                0,
                true
            )
            """
        )
    )

    # ============================================================
    # 8. REFERRALS
    # ============================================================

    op.create_table(
        "referrals",

        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),

        sa.Column(
            "referrer_user_id",
            sa.Uuid(),
            nullable=False,
        ),

        sa.Column(
            "referred_user_id",
            sa.Uuid(),
            nullable=False,
        ),

        sa.Column(
            "referral_code",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "reward_amount",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="0",
        ),

        sa.Column(
            "reward_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),

        sa.Column(
            "reward_transaction_reference",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "rewarded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["referrer_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["referred_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint("id"),

        sa.UniqueConstraint(
            "referred_user_id",
            name="uq_referrals_referred_user_id",
        ),

        sa.UniqueConstraint(
            "reward_transaction_reference",
            name="uq_referrals_reward_transaction_reference",
        ),
    )

    op.create_index(
        "ix_referrals_referrer_user_id",
        "referrals",
        ["referrer_user_id"],
    )

    op.create_index(
        "ix_referrals_referred_user_id",
        "referrals",
        ["referred_user_id"],
    )

    op.create_index(
        "ix_referrals_referral_code",
        "referrals",
        ["referral_code"],
    )

    op.create_index(
        "ix_referrals_reward_status",
        "referrals",
        ["reward_status"],
    )

    # ============================================================
    # 9. PLATFORM / ADMIN WALLET
    # ============================================================

    op.create_table(
        "platform_wallets",

        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),

        sa.Column(
            "wallet_number",
            sa.String(length=30),
            nullable=False,
        ),

        sa.Column(
            "currency",
            sa.String(length=10),
            nullable=False,
            server_default="NGN",
        ),

        sa.Column(
            "balance",
            sa.Numeric(20, 2),
            nullable=False,
            server_default="0",
        ),

        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),

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

        sa.PrimaryKeyConstraint("id"),

        sa.UniqueConstraint(
            "wallet_number",
            name="uq_platform_wallets_wallet_number",
        ),
    )

    op.create_index(
        "ix_platform_wallets_wallet_number",
        "platform_wallets",
        ["wallet_number"],
        unique=True,
    )

    # ============================================================
    # 10. CREATE DEFAULT ONTIME ADMIN WALLET
    #
    # IMPORTANT:
    # PostgreSQL column is UUID.
    # Therefore we explicitly cast the parameter to UUID.
    # ============================================================

    admin_wallet_id = uuid.UUID(
        "8c3a3f1d-0b8d-4c1f-9d9e-8d8a1a0a0001"
    )

    op.execute(
    sa.text(
        """
        INSERT INTO platform_wallets
        (
            id,
            wallet_number,
            currency,
            balance,
            status
        )
        VALUES
        (
            CAST(:id AS UUID),
            :wallet_number,
            'NGN',
            0,
            'active'
        )
        """
    ).bindparams(
        id=str(admin_wallet_id),
        wallet_number="ADMIN-ONTIME-0001",
    )
)

    # ============================================================
    # 11. PLATFORM WALLET TRANSACTIONS / LEDGER
    # ============================================================

    op.create_table(
        "platform_transactions",

        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),

        sa.Column(
            "platform_wallet_id",
            sa.Uuid(),
            nullable=False,
        ),

        sa.Column(
            "admin_id",
            sa.Uuid(),
            nullable=True,
        ),

        sa.Column(
            "reference",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "transaction_type",
            sa.String(length=40),
            nullable=False,
        ),

        sa.Column(
            "direction",
            sa.String(length=20),
            nullable=False,
        ),

        sa.Column(
            "amount",
            sa.Numeric(20, 2),
            nullable=False,
        ),

        sa.Column(
            "balance_before",
            sa.Numeric(20, 2),
            nullable=False,
        ),

        sa.Column(
            "balance_after",
            sa.Numeric(20, 2),
            nullable=False,
        ),

        sa.Column(
            "currency",
            sa.String(length=10),
            nullable=False,
            server_default="NGN",
        ),

        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="completed",
        ),

        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["platform_wallet_id"],
            ["platform_wallets.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admins.id"],
            ondelete="SET NULL",
        ),

        sa.PrimaryKeyConstraint("id"),

        sa.UniqueConstraint(
            "reference",
            name="uq_platform_transactions_reference",
        ),
    )

    op.create_index(
        "ix_platform_transactions_platform_wallet_id",
        "platform_transactions",
        ["platform_wallet_id"],
    )

    op.create_index(
        "ix_platform_transactions_admin_id",
        "platform_transactions",
        ["admin_id"],
    )

    op.create_index(
        "ix_platform_transactions_reference",
        "platform_transactions",
        ["reference"],
        unique=True,
    )

    op.create_index(
        "ix_platform_transactions_created_at",
        "platform_transactions",
        ["created_at"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:

    # Platform transactions
    op.drop_index(
        "ix_platform_transactions_created_at",
        table_name="platform_transactions",
    )

    op.drop_index(
        "ix_platform_transactions_reference",
        table_name="platform_transactions",
    )

    op.drop_index(
        "ix_platform_transactions_admin_id",
        table_name="platform_transactions",
    )

    op.drop_index(
        "ix_platform_transactions_platform_wallet_id",
        table_name="platform_transactions",
    )

    op.drop_table("platform_transactions")

    # Platform wallet
    op.drop_index(
        "ix_platform_wallets_wallet_number",
        table_name="platform_wallets",
    )

    op.drop_table("platform_wallets")

    # Referrals
    op.drop_index(
        "ix_referrals_reward_status",
        table_name="referrals",
    )

    op.drop_index(
        "ix_referrals_referral_code",
        table_name="referrals",
    )

    op.drop_index(
        "ix_referrals_referred_user_id",
        table_name="referrals",
    )

    op.drop_index(
        "ix_referrals_referrer_user_id",
        table_name="referrals",
    )

    op.drop_table("referrals")

    # Referral settings
    op.drop_table("referral_settings")

    # Wallet
    op.drop_index(
        "ix_wallets_wallet_number",
        table_name="wallets",
    )

    # User referral foreign key
    op.drop_constraint(
        "fk_users_referred_by_id",
        "users",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_users_referred_by_id",
        table_name="users",
    )

    op.drop_index(
        "ix_users_referral_code",
        table_name="users",
    )

    # Columns
    op.drop_column(
        "wallets",
        "wallet_number",
    )

    op.drop_column(
        "users",
        "referred_by_id",
    )

    op.drop_column(
        "users",
        "referral_code",
    )