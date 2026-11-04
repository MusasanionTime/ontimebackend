# ONTIME SUBDATA LTD Backend Conversion

## Registration
- Removed BVN/NIN requirements from customer registration.
- Removed Monnify virtual/bank account creation from the registration flow.
- Every newly registered user automatically receives an internal unique wallet number.
- Customer wallet starts at NGN 0.00 and is created in the same database transaction as the user.
- Registration accepts an optional referral code.

## Wallet
- Added `wallet_number` to customer wallets.
- Added unique wallet-number generation with the `82XXXXXXXX` format.
- Existing wallets are backfilled during migration.
- Existing wallet ledger/transaction architecture is preserved.

## Referral System
- Every user receives a unique referral code.
- Referral code can be supplied during registration.
- Referred users are tracked.
- Admin can enable/disable the referral program.
- Admin can configure fixed or percentage rewards, qualifying amount and first-transaction rules.
- Referral rewards are credited to the referrer's wallet only for qualifying wallet funding/deposit transactions.
- Customer referral summary and history endpoints added.
- Admin referral list, summary and settings endpoints added.

## Admin / Platform Wallet
- Added a separate platform/admin wallet, independent from customer wallets.
- Added platform wallet ledger with credit/debit transactions.
- Added admin audit logging for platform-wallet adjustments.
- Added admin endpoints for customer-wallet credit/debit with audit logging.
- Platform wallet is created by migration as `ADMIN-ONTIME-0001` with zero balance.

## Branding
- API project name changed to ONTIME SUBDATA LTD.
- Email/reset messaging and relevant Alpha Galaxy references were updated.
- `.env` is intentionally excluded from the packaged handoff; configure secrets using `.env.example`.

## Migration
Run:

```bash
alembic upgrade head
```

New migration:
`8b2d1e9c4a10_ontime_wallet_referral_platform_wallet.py`

## Important
This conversion intentionally does not create a bank/virtual account during registration. Payment-provider funding can remain a separate flow and can be configured later without making BVN/NIN part of normal account registration.
