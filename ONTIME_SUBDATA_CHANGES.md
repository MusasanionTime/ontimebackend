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

## Wallet funding with Monnify Dynamic Invoices
- Customer funding now uses `POST /api/v1/wallet/deposits/initialize` to create a single-use Dynamic Invoice and bank account for each deposit. This does not request BVN/NIN and does not change customer registration.
- The response includes Monnify's invoice `accountNumber`, `accountName`, `bankName`, and `bankCode`, plus checkout URL and expiry when returned.
- Customers can view their deposit history at `GET /api/v1/wallet/deposits`, inspect one deposit at `GET /api/v1/wallet/deposits/{reference}`, and request a server-side status check with `POST /api/v1/wallet/deposits/{reference}/verify`.
- Configure Monnify's Transaction Completion webhook to `POST /api/v1/payments/webhooks/monnify`. Production requests must include a valid `monnify-signature` HMAC-SHA512. Sandbox omits the header in Monnify's documented behavior; unsigned notifications are accepted only when `DEBUG=True` and the configured host contains `sandbox`.
- Webhook payloads only trigger an independent Monnify transaction query. The wallet is credited exactly once after that query reports `PAID`, NGN, and the exact invoice amount. The transaction ledger and referral reward are committed together.
- Admins can monitor deposits at `GET /api/v1/admin/deposits` and reconcile an individual deposit against Monnify at `POST /api/v1/admin/deposits/{reference}/reconcile`.
- `transactions.provider_metadata` stores invoice transfer details and is added by migration `c41798f4b20a`.
- Monnify's Create Invoice request documentation does not define a `customerPaysFee` request field. The implementation does not send one. Applicable fee responsibility is controlled by the merchant contract/payment method at Monnify; the wallet credit remains the requested deposit amount while Monnify verifies that exact invoice amount.
- Required deployment variables: `MONNIFY_BASE_URL`, `MONNIFY_API_KEY`, `MONNIFY_SECRET_KEY`, `MONNIFY_CONTRACT_CODE`, and `FRONTEND_URL`. Never deploy the example values or commit `.env`.

## Important
This conversion intentionally does not create a bank/virtual account during registration. Payment-provider funding can remain a separate flow and can be configured later without making BVN/NIN part of normal account registration.
