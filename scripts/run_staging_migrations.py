"""Run Alembic only against the explicitly named ONTIME staging database."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


EXPECTED_DATABASE = "ontime_commission_staging"


def main() -> int:
    raw_url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not raw_url:
        print("Refusing migration: set TEST_DATABASE_URL to the dedicated staging database.", file=sys.stderr)
        return 2

    try:
        url = make_url(raw_url)
    except Exception:
        print("Refusing migration: TEST_DATABASE_URL is not a valid PostgreSQL URL.", file=sys.stderr)
        return 2

    if url.get_backend_name() != "postgresql":
        print("Refusing migration: TEST_DATABASE_URL must use PostgreSQL.", file=sys.stderr)
        return 2
    if (url.database or "").lower() != EXPECTED_DATABASE:
        print(f"Refusing migration: database name must be {EXPECTED_DATABASE}.", file=sys.stderr)
        return 2
    if not url.host or any(marker in url.host.lower() for marker in ("railway", "rlwy")):
        print("Refusing migration: missing host or a Railway host was detected.", file=sys.stderr)
        return 2

    # Explicitly override DATABASE_URL for the child Alembic environment.
    # The `.env` file and any previously configured application URL are never
    # selected as migration targets by this script.
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            database_name, version_num = connection.execute(
                text("SELECT current_database(), current_setting('server_version_num')::integer")
            ).one()
            if database_name != EXPECTED_DATABASE:
                print("Refusing migration: connected database does not match the required staging database.", file=sys.stderr)
                return 2
            if version_num < 140000:
                print("Refusing migration: PostgreSQL 14 or newer is required.", file=sys.stderr)
                return 2
            version = connection.execute(text("SHOW server_version")).scalar_one()
            print(f"Verified isolated staging target on PostgreSQL {version}; applying Alembic head.")

        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            global_config = connection.execute(text(
                "SELECT is_enabled, commission_value FROM commission_configurations "
                "WHERE service_key = 'global' ORDER BY revision DESC LIMIT 1"
            )).one_or_none()
            service_rate_count = connection.execute(text(
                "SELECT count(*) FROM commission_configurations "
                "WHERE service_key <> 'global' AND commission_value IS NOT NULL"
            )).scalar_one()
        if global_config is None or global_config.is_enabled or global_config.commission_value is not None:
            print("Migration reached head, but the global commission default is not safely disabled.", file=sys.stderr)
            return 1
        if service_rate_count:
            print("Migration reached head, but configured service rates were found; review the isolated target.", file=sys.stderr)
            return 1
        print("Staging migration completed and verified: global commission disabled, no service rates configured.")
        return 0
    except Exception:
        # Avoid exception text here: database drivers can include connection
        # details in low-level errors. The process exit status signals failure.
        print("Staging migration failed; details suppressed to protect connection credentials.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
