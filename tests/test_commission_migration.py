import importlib.util
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


def test_purchase_commission_migration_upgrade_and_downgrade_on_isolated_sqlite():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "e2f471c39a60_add_purchase_commissions.py"
    )
    spec = importlib.util.spec_from_file_location("commission_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        metadata = sa.MetaData()
        for table_name in ("admins", "users", "transactions", "platform_wallets", "platform_transactions"):
            sa.Table(table_name, metadata, sa.Column("id", sa.Uuid(), primary_key=True))
        metadata.create_all(connection)

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        inspector = inspect(connection)
        assert {"commission_configurations", "purchase_commissions", "commission_reversals"}.issubset(
            set(inspector.get_table_names())
        )
        config_cols = {column["name"] for column in inspector.get_columns("commission_configurations")}
        assert {"service_key", "revision", "commission_value", "effective_from"}.issubset(config_cols)
        default_row = connection.execute(
            sa.text("SELECT service_key, is_enabled, commission_value FROM commission_configurations")
        ).one()
        assert default_row.service_key == "global"
        assert bool(default_row.is_enabled) is False
        assert default_row.commission_value is None

        with Operations.context(context):
            migration.downgrade()
        tables_after_downgrade = set(inspect(connection).get_table_names())
        assert not {"commission_configurations", "purchase_commissions", "commission_reversals"}.intersection(
            tables_after_downgrade
        )
    engine.dispose()
