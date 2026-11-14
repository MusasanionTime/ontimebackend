# Topify integration

The Topify integration is isolated from Monnify and is configured from environment variables. The first supported account rail is Moniepoint only (`bankCode: ["30901"]`). Reservation sends only `email`, `name`, `phoneNumber`, `bankCode`, and the configured `businessId`; it never sends BVN, NIN, PalmPay identity fields, or other customer identity numbers.

## Configuration

Set these variables in the backend environment. Keep both secrets server-side and do not commit them:

| Variable | Purpose |
| --- | --- |
| `TOPIFY_ENABLED` | Explicit feature switch; leave `false` until credentials and business approval are ready. |
| `TOPIFY_BASE_URL` | Topify API host, normally `https://apipay.topify.ng` for test and live keys. |
| `TOPIFY_API_KEY` | Server-side `sk_test_...` sandbox key or, after approval, `sk_live_...` key. |
| `TOPIFY_WEBHOOK_SECRET` | Separate webhook secret configured in Topify Developer Settings. |
| `TOPIFY_BUSINESS_ID` | Approved business ID from the Topify dashboard; required for account reservation. |

Topify documents the same API host for test and live keys. Use a test key and dashboard test events before production. Code does not provision an account unless the feature is enabled and a business ID is configured. No business approval or live reservation is implied by this implementation.

## Customer endpoints

All customer endpoints use the existing ONTIME bearer authentication.

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/topify/accounts/reserve` | Reserve a Moniepoint-only dedicated account for the signed-in customer. Retries reuse the same stored email/name/phone tuple as Topify's documented idempotency key. |
| `GET /api/v1/topify/accounts/me` | Retrieve the ONTIME account record for the signed-in customer. |
| `GET /api/v1/topify/accounts/me/provider` | Retrieve active accounts from Topify using the stored customer code; callers cannot supply another customer's code. |
| `GET /api/v1/topify/transactions/{reference}/verify` | Verify a Topify reference already recorded against the signed-in customer's wallet. It does not credit an unowned or unrecorded reference. |
| `POST /api/v1/topify/webhooks` | Receive signed Topify events. Configure this public HTTPS URL in the Topify dashboard. |

## Settlement and event rules

- Webhook HMAC-SHA512 uses the exact raw request body and `X-Topify-Signature`, compared in constant time. Missing secrets/signatures are rejected in every environment.
- `charge.success` is verified against `GET /api/v1/transactions/verify/{reference}` before a wallet credit. Topify amounts are JSON integers in kobo. The customer receives `amount - fee`, converted exactly to naira with `Decimal`; the choice to credit net of the fee is intentional. Currency must be `NGN` and the net must be positive.
- The transaction reference is deterministically namespaced and the existing wallet row lock and unique transaction reference prevent duplicate credits. `X-Topify-Delivery` is stored with a unique constraint for delivery-level replay handling; the payment reference also prevents a second credit if Topify retries using a new delivery ID.
- `wallet.funded`, `charge.failed`, and `customer.virtual_account.created` are verified, deduplicated, and safely audited. `wallet.funded` does not cause a second credit; `charge.success` is the sole credit event. Failure/account events do not move customer funds.
- `transaction.reversed` marks the matching Topify transaction as reversed but does not change the wallet balance, as specified. The webhook event and transaction metadata retain the reversal signal.
- The handler stores only allowlisted, non-PII audit metadata and never stores raw webhook bodies.
- If Topify verification is unavailable, the webhook returns an error so Topify can retry. Terminal mismatches are recorded for reconciliation without credit. Reservation timeouts leave the account pending; retry with the unchanged customer details to take advantage of Topify's documented reserve idempotency. Verify recorded payments with the customer transaction endpoint.

## Migration and checks

Apply the new tables with:

```powershell
python -m alembic upgrade head
```

The migration adds `topify_accounts` and `topify_webhook_events`; it does not alter Monnify or wallet tables. Run the focused Topify and wallet tests with:

```powershell
python -m pytest -q tests/test_topify.py tests/test_wallet_idempotency.py
```

Before live use, ONTIME must be approved by Topify, obtain the approved business ID and live API key, configure the webhook secret and public HTTPS callback, and complete sandbox verification. The docs list `transaction.reversed` but do not provide its payload schema; the handler only acts on `data.reference` matching an existing Topify ledger transaction and does not debit the wallet.
