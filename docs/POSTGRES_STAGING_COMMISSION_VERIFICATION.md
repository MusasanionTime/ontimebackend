# ONTIME commission PostgreSQL staging verification

## Database target and prerequisites

- Use a newly created, isolated PostgreSQL database named exactly `ontime_commission_staging` on a non-production host. The tooling rejects other database names and hostnames containing `railway` or `rlwy`.
- PostgreSQL 14 or newer is required. The PostgreSQL client binaries installed on the current workstation report version 18.7; no server was available to query.
- Use the `psycopg` or `psycopg2` SQLAlchemy driver. The requirements include `psycopg[binary]` and `psycopg2-binary`.
- The database role needs CONNECT and DDL privileges to run the full Alembic chain. The integration suite additionally creates and drops one randomly named isolated schema, so its role needs CREATE/DROP schema privileges in this disposable staging database.
- For remote databases, use the SSL options required by the staging provider. Never point this workflow at a Railway URL or a database containing production data.

The environment variable is `TEST_DATABASE_URL`. Its value must be a PostgreSQL URL for the dedicated database, for example the shape `postgresql+psycopg://USER:PASSWORD@STAGING_HOST:5432/ontime_commission_staging`. Keep the value in the local shell or secret manager; do not paste it into chat or logs.

## Safe PowerShell sequence

Populate `TEST_DATABASE_URL` locally (replace placeholders in your secret manager or shell profile; do not send the value in chat), then run:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://<user>:<password>@<non-railway-staging-host>:5432/ontime_commission_staging'
if (-not $env:TEST_DATABASE_URL) { throw 'Set TEST_DATABASE_URL to the dedicated staging database first.' }
.\.venv\Scripts\python.exe scripts\run_staging_migrations.py
if ($LASTEXITCODE -ne 0) { throw 'Staging migration did not complete safely.' }
.\.venv\Scripts\python.exe -m pytest -q -m postgresql tests\test_commissions_postgresql.py
```

`run_staging_migrations.py` requires the exact database name `ontime_commission_staging`, rejects Railway-like hostnames, verifies the connected database name and PostgreSQL version, sets `DATABASE_URL` only in its own process from `TEST_DATABASE_URL`, migrates to Alembic head, and verifies the global switch is off and no service rates are configured. It never prints the URL or password.

The migration runner overrides `DATABASE_URL` only inside its own process. The integration fixture independently validates `TEST_DATABASE_URL`, passes its isolated connection directly into Alembic, creates a unique schema, migrates that schema to head, runs synthetic tests there, and drops only that schema at teardown. The Alembic environment does not import application settings or construct a default database engine when an external test connection is supplied. The tests do not call BigiSub or any live provider.

The original SQLite tests remain unchanged. When `TEST_DATABASE_URL` is absent, PostgreSQL integration tests skip; no migration runs.

## PostgreSQL integration coverage

The PostgreSQL test module covers migration defaults; disabled proposed rates; the four percentage examples; concurrent purchase callbacks; concurrent refunds; unique commission and platform-ledger references; `FOR UPDATE` row locks and READ COMMITTED visibility; rollback on ledger posting failure; and insufficient platform funds during reversal. These tests only run when the guarded test URL is present.
