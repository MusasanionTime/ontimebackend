
"""Run Alembic only against the explicitly verified ONTIME Neon staging branch."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
STAGING_ENV = ROOT / ".env.staging"

EXPECTED_DATABASE = "neondb"

EXPECTED_HOSTS = {
    "ep-old-flower-bdj55qjk.c-8.us-east-2.aws.neon.tech",
    "ep-old-flower-bdj55qjk-pooler.c-8.us-east-2.aws.neon.tech",
}

EXPECTED_BRANCH = "staging"
EXPECTED_BRANCH_ID = "br-solitary-bread-bdmj0u9l"
EXPECTED_REVISION = "e2f471c39a60"


def refuse(message: str) -> int:
    print(f"Refusing migration: {message}", file=sys.stderr)
    return 2


def main() -> int:
    if not STAGING_ENV.is_file():
        return refuse(".env.staging was not found.")

    # Load only the dedicated staging environment.
    # Staging values override existing Windows environment variables.
    # Production .env is never loaded.
    load_dotenv(STAGING_ENV, override=True)

    if os.environ.get("NEON_BRANCH") != EXPECTED_BRANCH:
        return refuse("Neon branch metadata does not identify staging.")

    if os.environ.get("NEON_BRANCH_ID") != EXPECTED_BRANCH_ID:
        return refuse("Neon branch ID does not match the approved staging branch.")

    # Only DATABASE_URL from .env.staging is accepted.
    raw_url = os.environ.get("DATABASE_URL", "").strip()

    if not raw_url:
        return refuse("No staging DATABASE_URL was found.")

    try:
        url = make_url(raw_url)
    except Exception:
        return refuse("The staging database URL is invalid.")

    if url.get_backend_name() != "postgresql":
        return refuse("Only PostgreSQL is permitted.")

    if (url.database or "").lower() != EXPECTED_DATABASE:
        return refuse("Database name does not match the approved staging database.")

    if (url.host or "").lower() not in EXPECTED_HOSTS:
        return refuse("Database host does not match the approved Neon staging endpoint.")

    # Ensure Alembic uses the verified staging connection.
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)

    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )

    try:
        with engine.connect() as connection:
            database_name, version_num = connection.execute(
                text(
                    "SELECT current_database(), "
                    "current_setting('server_version_num')::integer"
                )
            ).one()

            if database_name != EXPECTED_DATABASE:
                return refuse("Connected database name did not match staging.")

            if version_num < 140000:
                return refuse("PostgreSQL 14 or newer is required.")

            version = connection.execute(
                text("SHOW server_version")
            ).scalar_one()

            print(
                f"Verified Neon staging target on PostgreSQL {version}. "
                "Applying Alembic head."
            )

        config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(config, "head")

        with engine.connect() as connection:
            global_config = connection.execute(
                text(
                    "SELECT is_enabled, commission_value "
                    "FROM commission_configurations "
                    "WHERE service_key = 'global' "
                    "ORDER BY revision DESC LIMIT 1"
                )
            ).one_or_none()

            service_rate_count = connection.execute(
                text(
                    "SELECT count(*) FROM commission_configurations "
                    "WHERE service_key <> 'global' "
                    "AND commission_value IS NOT NULL"
                )
            ).scalar_one()

            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        if revision != EXPECTED_REVISION:
            print(
                "Migration did not reach the expected Alembic head.",
                file=sys.stderr,
            )
            return 1

        if (
            global_config is None
            or global_config.is_enabled
            or global_config.commission_value is not None
        ):
            print(
                "Global commission default is not safely disabled.",
                file=sys.stderr,
            )
            return 1

        if service_rate_count:
            print(
                "Unexpected configured commission rates were found.",
                file=sys.stderr,
            )
            return 1

        print("Staging migration completed successfully.")
        print("Alembic revision verified.")
        print("Global commissions remain disabled.")
        print("No service commission rates are configured.")

        return 0

    except Exception:
        print(
            "Staging migration failed. Error details suppressed to protect credentials.",
            file=sys.stderr,
        )
        return 1

    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
