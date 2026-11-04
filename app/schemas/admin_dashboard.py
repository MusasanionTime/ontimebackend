from decimal import Decimal

from pydantic import BaseModel


class AdminDashboardOverview(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    verified_users: int
    unverified_users: int

    total_wallets: int
    active_wallets: int
    inactive_wallets: int
    total_wallet_balance: Decimal

    total_transactions: int
    pending_transactions: int
    successful_transactions: int
    failed_transactions: int

    total_crypto_exchanges: int
    pending_crypto_exchanges: int
    completed_crypto_exchanges: int

    total_monnify_accounts: int
    active_monnify_accounts: int
    pending_monnify_accounts: int