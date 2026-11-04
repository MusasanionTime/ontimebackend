# BigiSub data purchase integration

The backend and Flutter source now include the data-purchase flow. The backend checks the customer's ONTIME transaction PIN locally, fetches the plan price from BigiSub, reserves the wallet balance, and records provider success/failure/pending states. The customer's PIN is never sent to BigiSub; the provider PIN is read from server configuration.

## Required server configuration before enabling purchases

Set these environment variables on the backend host (do not put them in Flutter):

- `BIGISUB_PROVIDER_PIN`: the PIN required by BigiSub's provider API. This is not the customer's ONTIME transaction PIN.
- `BIGISUB_DATA_PURCHASE_PATH`: the exact data-purchase path for the same legacy API version that serves `/api/v2/vtu/data/plans/`. This is intentionally blank by default because the uploaded example included a request/response but did not establish the exact legacy purchase URL.

The purchase route returns HTTP 503 until both are configured. Confirm the exact path in BigiSub Settings > API Doc before enabling it. Existing catalogue loading is unchanged.

## Flutter request

Flutter calls `POST /api/v1/bigisub/data/purchase` with `network`, `plan`, `phone_number`, `transaction_pin`, and `ported_number`. The backend maps `transaction_pin` to local authorization and separately adds `BIGISUB_PROVIDER_PIN` as the provider's `pin`.

## Transaction safety

- Plan price is looked up on the backend; the client cannot submit its own price.
- The wallet is reserved before calling the provider.
- Confirmed success completes the transaction.
- Explicit provider rejection creates a refund ledger entry.
- Network errors/uncertain outcomes remain pending and are not automatically refunded, to avoid duplicate purchases. These pending transactions require reconciliation.

## Test

From the backend project directory, run `python -m compileall -q app`. Then run the API locally and verify the catalogue endpoint. Do not test a live purchase until the exact path and provider PIN have been confirmed.
