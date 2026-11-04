from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.crypto_exchange import CryptoExchange
from app.models.monnify_account import MonnifyAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.admin_dashboard import AdminDashboardOverview


def get_dashboard_overview(db: Session) -> AdminDashboardOverview:
    total_users = db.scalar(
        select(func.count(User.id))
    ) or 0

    active_users = db.scalar(
        select(func.count(User.id)).where(User.is_active.is_(True))
    ) or 0

    inactive_users = db.scalar(
        select(func.count(User.id)).where(User.is_active.is_(False))
    ) or 0

    verified_users = db.scalar(
        select(func.count(User.id)).where(User.is_verified.is_(True))
    ) or 0

    unverified_users = db.scalar(
        select(func.count(User.id)).where(User.is_verified.is_(False))
    ) or 0

    total_wallets = db.scalar(
        select(func.count(Wallet.id))
    ) or 0

    active_wallets = db.scalar(
        select(func.count(Wallet.id)).where(Wallet.status == "active")
    ) or 0

    inactive_wallets = db.scalar(
        select(func.count(Wallet.id)).where(Wallet.status != "active")
    ) or 0

    total_wallet_balance = db.scalar(
        select(func.coalesce(func.sum(Wallet.balance), 0))
    ) or Decimal("0.00")

    total_transactions = db.scalar(
        select(func.count(Transaction.id))
    ) or 0

    pending_transactions = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.status == "pending"
        )
    ) or 0

    successful_transactions = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.status.in_(["successful", "success", "completed"])
        )
    ) or 0

    failed_transactions = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.status.in_(["failed", "failure"])
        )
    ) or 0

    total_crypto_exchanges = db.scalar(
        select(func.count(CryptoExchange.id))
    ) or 0

    pending_crypto_exchanges = db.scalar(
        select(func.count(CryptoExchange.id)).where(
            CryptoExchange.status.in_(
                ["waiting", "confirming", "exchanging"]
            )
        )
    ) or 0

    completed_crypto_exchanges = db.scalar(
        select(func.count(CryptoExchange.id)).where(
            CryptoExchange.status.in_(
                ["finished", "completed"]
            )
        )
    ) or 0

    total_monnify_accounts = db.scalar(
        select(func.count(MonnifyAccount.id))
    ) or 0

    active_monnify_accounts = db.scalar(
        select(func.count(MonnifyAccount.id)).where(
            MonnifyAccount.status == "active"
        )
    ) or 0

    pending_monnify_accounts = db.scalar(
        select(func.count(MonnifyAccount.id)).where(
            MonnifyAccount.status == "pending"
        )
    ) or 0

    return AdminDashboardOverview(
        total_users=total_users,
        active_users=active_users,
        inactive_users=inactive_users,
        verified_users=verified_users,
        unverified_users=unverified_users,
        total_wallets=total_wallets,
        active_wallets=active_wallets,
        inactive_wallets=inactive_wallets,
        total_wallet_balance=total_wallet_balance,
        total_transactions=total_transactions,
        pending_transactions=pending_transactions,
        successful_transactions=successful_transactions,
        failed_transactions=failed_transactions,
        total_crypto_exchanges=total_crypto_exchanges,
        pending_crypto_exchanges=pending_crypto_exchanges,
        completed_crypto_exchanges=completed_crypto_exchanges,
        total_monnify_accounts=total_monnify_accounts,
        active_monnify_accounts=active_monnify_accounts,
        pending_monnify_accounts=pending_monnify_accounts,
    )