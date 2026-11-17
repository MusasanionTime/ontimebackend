
"""PostgreSQL-only integration tests for purchase commissions.

Uses only the dedicated ontime_commission_staging database.
Each test gets a separate temporary schema. The public schema and
production Railway database are not modified.
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
EXPECTED_DATABASE = "ontime_commission_staging"

pytestmark = pytest.mark.postgresql


def _validated_url():
    if not TEST_DATABASE_URL:
        pytest.skip("PostgreSQL integration tests require TEST_DATABASE_URL.")

    try:
        url = make_url(TEST_DATABASE_URL)
    except Exception:
        pytest.fail(
            "TEST_DATABASE_URL must be a valid PostgreSQL URL (value suppressed)."
        )

    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_DATABASE_URL must target PostgreSQL (value suppressed).")

    if (url.database or "").lower() != EXPECTED_DATABASE:
        pytest.fail(
            f"PostgreSQL integration tests require database {EXPECTED_DATABASE}."
        )

    if not url.host or any(
        marker in url.host.lower() for marker in ("railway", "rlwy")
    ):
        pytest.fail(
            "TEST_DATABASE_URL host is missing or is a Railway host (value suppressed)."
        )

    return url


@pytest.fixture(scope="function")
def pg():
    """Create a disposable schema and migrate it for one test."""

    url = _validated_url()

    root_engine = create_engine(
        url,
        poolclass=NullPool,
        connect_args={"connect_timeout": 10},
    )

    schema = f"commission_it_{uuid.uuid4().hex}"
    engine = None

    try:
        with root_engine.begin() as connection:
            db_name, version_num = connection.execute(
                text(
                    "SELECT current_database(), "
                    "current_setting('server_version_num')::integer"
                )
            ).one()

            version_text = connection.exec_driver_sql(
                "SHOW server_version"
            ).scalar_one()

            if db_name != EXPECTED_DATABASE:
                pytest.fail(
                    "Connected PostgreSQL database name did not match staging."
                )

            if version_num < 140000:
                pytest.fail("PostgreSQL 14 or newer is required.")

            connection.exec_driver_sql(
                f'CREATE SCHEMA "{schema}"'
            )

        # The startup option applies search_path to every physical connection,
        # including connections created by concurrent test workers.
        engine = create_engine(
            url,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 10,
                "options": f"-csearch_path={schema}",
            },
        )

        alembic_config = Config(
            str(Path(__file__).parents[1] / "alembic.ini")
        )

        with engine.connect() as connection:
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")

        factory = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )

        yield {
            "engine": engine,
            "sessions": factory,
            "schema": schema,
            "version": version_text,
        }

    finally:
        if engine is not None:
            engine.dispose()

        with root_engine.begin() as connection:
            connection.exec_driver_sql(
                f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'
            )

        root_engine.dispose()


@pytest.fixture
def db(pg):
    """Provide a database session for the current isolated schema."""

    session = pg["sessions"]()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _seed_purchase(
    db,
    *,
    amount=Decimal("100.00"),
    category="data",
    purchase_amount: Decimal | None = None,
):
    from app.models.transaction import Transaction
    from app.models.user import User
    from app.models.wallet import Wallet

    user_id = uuid.uuid4()

    user = User(
        id=user_id,
        email=f"{user_id.hex}@integration.test",
        phone=None,
        password_hash="integration-test",
        referral_code=f"I{user_id.hex[:12]}",
        is_active=True,
    )

    db.add(user)
    db.flush()

    wallet = Wallet(
        id=uuid.uuid4(),
        user_id=user_id,
        wallet_number=f"IT-{user_id.hex[:20]}",
        currency="NGN",
        balance=Decimal("0.00"),
        status="active",
    )

    db.add(wallet)
    db.flush()

    tx = Transaction(
        id=uuid.uuid4(),
        wallet_id=wallet.id,
        reference=f"IT-{uuid.uuid4().hex}",
        transaction_type=f"{category}_purchase",
        direction="debit",
        amount=amount,
        balance_before=amount,
        balance_after=Decimal("0.00"),
        currency="NGN",
        status="pending",
        provider="bigisub",
        provider_metadata={
            "commission_purchase_amount": str(
                purchase_amount if purchase_amount is not None else amount
            )
        },
    )

    db.add(tx)
    db.commit()

    return user, wallet, tx


def _enable_commission(
    db,
    *,
    category="data",
    rate=Decimal("2.000000"),
):
    from app.models.commission import CommissionConfiguration

    now = datetime.now(timezone.utc)

    current_revision = db.scalar(
        select(func.max(CommissionConfiguration.revision)).where(
            CommissionConfiguration.service_key == "global"
        )
    ) or 0

    db.add(
        CommissionConfiguration(
            id=uuid.uuid4(),
            service_key="global",
            revision=current_revision + 1,
            is_enabled=True,
            effective_from=now,
            reason="Integration-test-only active policy in disposable schema.",
        )
    )

    current_revision = db.scalar(
        select(func.max(CommissionConfiguration.revision)).where(
            CommissionConfiguration.service_key == category
        )
    ) or 0

    db.add(
        CommissionConfiguration(
            id=uuid.uuid4(),
            service_key=category,
            revision=current_revision + 1,
            is_enabled=True,
            calculation_type="percentage",
            commission_value=rate,
            calculation_basis="customer_purchase_amount",
            effective_from=now,
            reason="Integration-test-only rate in disposable schema.",
        )
    )

    db.commit()


def _confirm(db, tx, category="data"):
    from app.commission.service import (
        finalize_confirmed_purchase,
        record_provider_success,
    )

    record_provider_success(
        db,
        purchase_transaction_id=tx.id,
        provider="bigisub",
        provider_reference=f"SYNTHETIC-{uuid.uuid4().hex}",
        service_category=category,
    )

    return finalize_confirmed_purchase(
        db,
        purchase_transaction_id=tx.id,
    )


# ---------------------------------------------------------------------
# Migration and configuration tests
# ---------------------------------------------------------------------


def test_postgres_migration_has_disabled_global_and_no_rates(pg, db):
    from app.models.commission import CommissionConfiguration

    global_row = db.scalar(
        select(CommissionConfiguration).where(
            CommissionConfiguration.service_key == "global"
        )
    )

    assert global_row is not None
    assert global_row.is_enabled is False
    assert global_row.commission_value is None

    assert db.scalar(
        select(func.count(CommissionConfiguration.id)).where(
            CommissionConfiguration.service_key != "global"
        )
    ) == 0

    assert pg["version"]


def test_proposed_rates_can_be_saved_disabled_in_staging(db):
    from app.models.commission import CommissionConfiguration

    rates = {
        "airtime": "2",
        "data": "2",
        "electricity": "1",
        "result_checker": "2",
    }

    for revision, (service, rate) in enumerate(rates.items(), start=1):
        db.add(
            CommissionConfiguration(
                id=uuid.uuid4(),
                service_key=service,
                revision=revision,
                is_enabled=False,
                calculation_type="percentage",
                commission_value=Decimal(rate),
                calculation_basis="customer_purchase_amount",
                effective_from=datetime.now(timezone.utc),
                reason="Proposed integration staging rate; keep disabled.",
            )
        )

    db.commit()

    service_configs = db.scalars(
        select(CommissionConfiguration).where(
            CommissionConfiguration.service_key != "global"
        )
    ).all()

    assert {
        row.service_key: row.commission_value for row in service_configs
    } == {
        key: Decimal(rate) for key, rate in rates.items()
    }

    assert all(not row.is_enabled for row in service_configs)

    assert db.scalar(
        select(CommissionConfiguration.is_enabled).where(
            CommissionConfiguration.service_key == "global"
        )
    ) is False


# ---------------------------------------------------------------------
# Commission calculation tests
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "category,purchase_amount,wallet_debit,rate,expected",
    [
        ("airtime", "1000.00", "1000.00", "2", "20.00"),
        ("data", "2000.00", "2000.00", "2", "40.00"),
        ("electricity", "5000.00", "5050.00", "1", "50.00"),
        ("result_checker", "1500.00", "1500.00", "2", "30.00"),
    ],
)
def test_postgres_proposed_rates_use_recorded_purchase_amount(
    db,
    category,
    purchase_amount,
    wallet_debit,
    rate,
    expected,
):
    from app.models.commission import PurchaseCommission

    _, _, tx = _seed_purchase(
        db,
        category=category,
        amount=Decimal(wallet_debit),
        purchase_amount=Decimal(purchase_amount),
    )

    _enable_commission(
        db,
        category=category,
        rate=Decimal(rate),
    )

    commission = _confirm(db, tx, category)

    assert commission.purchase_amount == Decimal(purchase_amount)
    assert commission.commission_amount == Decimal(expected)

    assert db.scalar(
        select(func.count(PurchaseCommission.id)).where(
            PurchaseCommission.source_transaction_id == tx.id
        )
    ) == 1


def test_postgres_unconfirmed_pending_and_failed_purchases_do_not_post(db):
    from fastapi import HTTPException
    from app.commission.service import finalize_confirmed_purchase
    from app.models.commission import PurchaseCommission
    from app.models.transaction import Transaction

    _, _, tx = _seed_purchase(db, category="data")

    _enable_commission(db, category="data")

    with pytest.raises(HTTPException) as error:
        finalize_confirmed_purchase(
            db,
            purchase_transaction_id=tx.id,
        )

    assert error.value.status_code == 409
    db.rollback()

    failed = db.get(Transaction, tx.id)
    failed.status = "failed"
    failed.provider_metadata = {
        "provider_success_confirmed": True
    }
    db.commit()

    with pytest.raises(HTTPException) as error:
        finalize_confirmed_purchase(
            db,
            purchase_transaction_id=tx.id,
        )

    assert error.value.status_code == 409
    db.rollback()

    assert db.scalar(
        select(func.count(PurchaseCommission.id)).where(
            PurchaseCommission.source_transaction_id == tx.id
        )
    ) == 0


# ---------------------------------------------------------------------
# Concurrent purchase callback test
# ---------------------------------------------------------------------


def test_postgres_concurrent_duplicate_purchase_callbacks_post_once(pg, db):
    from app.models.commission import PurchaseCommission
    from app.models.platform_wallet import (
        PlatformTransaction,
        PlatformWallet,
    )

    _, _, tx = _seed_purchase(
        db,
        amount=Decimal("2000.00"),
        category="data",
    )

    _enable_commission(
        db,
        category="data",
        rate=Decimal("2"),
    )

    tx_id = tx.id
    barrier = threading.Barrier(2)

    def callback():
        session = pg["sessions"]()

        try:
            barrier.wait(timeout=10)

            from app.commission.service import (
                finalize_confirmed_purchase,
                record_provider_success,
            )

            record_provider_success(
                session,
                purchase_transaction_id=tx_id,
                provider="bigisub",
                provider_reference=f"SYNTHETIC-{uuid.uuid4().hex}",
                service_category="data",
            )

            commission = finalize_confirmed_purchase(
                session,
                purchase_transaction_id=tx_id,
            )

            return commission.id

        finally:
            session.rollback()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(
            executor.map(lambda _: callback(), range(2))
        )

    assert ids[0] == ids[1]

    assert db.scalar(
        select(func.count(PurchaseCommission.id)).where(
            PurchaseCommission.source_transaction_id == tx_id
        )
    ) == 1

    assert db.scalar(
        select(func.count(PlatformTransaction.id)).where(
            PlatformTransaction.reference == f"PCOM-{tx_id.hex.upper()}"
        )
    ) == 1

    assert db.scalar(
        select(PlatformWallet.balance)
    ) == Decimal("40.00")


# ---------------------------------------------------------------------
# Concurrent refund callback test
# ---------------------------------------------------------------------


def test_postgres_concurrent_refund_callbacks_reverse_once(pg, db):
    from app.models.commission import CommissionReversal
    from app.models.platform_wallet import (
        PlatformTransaction,
        PlatformWallet,
    )
    from app.models.transaction import Transaction
    from app.wallet.service import WalletService

    _, wallet, tx = _seed_purchase(
        db,
        amount=Decimal("100.00"),
        category="data",
    )

    _enable_commission(
        db,
        category="data",
        rate=Decimal("2"),
    )

    commission = _confirm(db, tx, category="data")

    tx_id = tx.id
    wallet_id = wallet.id
    refund_ref = f"{tx.reference}-REFUND"

    db.execute(
        update(Transaction)
        .where(Transaction.id == tx_id)
        .values(status="failed")
    )
    db.commit()

    barrier = threading.Barrier(2)

    def refund_callback():
        session = pg["sessions"]()

        try:
            barrier.wait(timeout=10)

            row = WalletService.credit(
                session,
                wallet_id=wallet_id,
                amount=Decimal("100.00"),
                reference=refund_ref,
                transaction_type="data_purchase_refund",
            )

            session.commit()
            return row.id

        finally:
            session.rollback()
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        refund_ids = list(
            executor.map(lambda _: refund_callback(), range(2))
        )

    assert refund_ids[0] == refund_ids[1]

    assert db.scalar(
        select(func.count(CommissionReversal.id)).where(
            CommissionReversal.commission_id == commission.id
        )
    ) == 1

    assert db.scalar(
        select(func.count(PlatformTransaction.id)).where(
            PlatformTransaction.reference == f"{commission.reference}-REV"
        )
    ) == 1

    assert db.scalar(
        select(PlatformWallet.balance)
    ) == Decimal("0.00")


# ---------------------------------------------------------------------
# Unique reference and ledger tests
# ---------------------------------------------------------------------


def test_postgres_unique_commission_and_platform_ledger_references(db):
    from app.models.commission import (
        CommissionConfiguration,
        PurchaseCommission,
    )
    from app.models.platform_wallet import (
        PlatformTransaction,
        PlatformWallet,
    )
    from app.platform_wallet.service import (
        credit_platform_wallet_system,
        get_or_create_platform_wallet,
    )

    _, _, tx1 = _seed_purchase(db, category="data")
    user2, wallet2, tx2 = _seed_purchase(db, category="airtime")

    _enable_commission(db, category="data")

    config_id = db.scalar(
        select(CommissionConfiguration.id)
        .where(CommissionConfiguration.service_key == "data")
        .order_by(CommissionConfiguration.revision.desc())
    )

    wallet = get_or_create_platform_wallet(db)
    db.commit()

    first = PurchaseCommission(
        id=uuid.uuid4(),
        reference="UNIQUE-COMMISSION-REFERENCE",
        customer_id=wallet2.user_id,
        source_transaction_id=tx2.id,
        configuration_id=config_id,
        platform_transaction_id=None,
        provider="bigisub",
        service_category="airtime",
        purchase_amount=Decimal("100.00"),
        calculation_type="percentage",
        calculation_value=Decimal("2"),
        calculation_basis="customer_purchase_amount",
        commission_amount=Decimal("2.00"),
        currency="NGN",
        status="posted",
    )

    db.add(first)
    db.commit()

    duplicate = PurchaseCommission(
        id=uuid.uuid4(),
        reference="UNIQUE-COMMISSION-REFERENCE",
        customer_id=user2.id,
        source_transaction_id=tx1.id,
        configuration_id=config_id,
        platform_transaction_id=None,
        provider="bigisub",
        service_category="data",
        purchase_amount=Decimal("100.00"),
        calculation_type="percentage",
        calculation_value=Decimal("2"),
        calculation_basis="customer_purchase_amount",
        commission_amount=Decimal("2.00"),
        currency="NGN",
        status="posted",
    )

    db.add(duplicate)

    with pytest.raises(IntegrityError):
        db.flush()

    db.rollback()

    credit_platform_wallet_system(
        db,
        amount=Decimal("1.00"),
        reference="UNIQUE-PLATFORM-LEDGER-REFERENCE",
        transaction_type="test_credit",
        description="Synthetic uniqueness test.",
    )

    db.commit()

    ledger = db.scalar(
        select(PlatformTransaction).where(
            PlatformTransaction.reference
            == "UNIQUE-PLATFORM-LEDGER-REFERENCE"
        )
    )

    duplicate_ledger = PlatformTransaction(
        id=uuid.uuid4(),
        platform_wallet_id=ledger.platform_wallet_id,
        admin_id=None,
        reference=ledger.reference,
        transaction_type="test_credit",
        direction="credit",
        amount=Decimal("1.00"),
        balance_before=ledger.balance_before,
        balance_after=ledger.balance_after,
        currency="NGN",
        status="completed",
    )

    db.add(duplicate_ledger)

    with pytest.raises(IntegrityError):
        db.flush()

    db.rollback()

    assert db.get(PlatformWallet, wallet.id) is not None


# ---------------------------------------------------------------------
# PostgreSQL row-locking and isolation test
# ---------------------------------------------------------------------


def test_postgres_for_update_locking_and_read_committed_isolation(pg, db):
    from app.models.wallet import Wallet

    _, wallet, _ = _seed_purchase(db)
    wallet_id = wallet.id

    locker = pg["sessions"]()
    contender = pg["sessions"]()

    try:
        assert db.execute(
            text("SHOW transaction_isolation")
        ).scalar_one() == "read committed"

        locked_wallet = locker.scalar(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .with_for_update()
        )

        assert locked_wallet is not None

        with pytest.raises(OperationalError):
            contender.scalar(
                select(Wallet)
                .where(Wallet.id == wallet_id)
                .with_for_update(nowait=True)
            )

        contender.rollback()

        locked_wallet.balance = Decimal("9.00")
        locker.commit()

        assert contender.scalar(
            select(Wallet.balance).where(Wallet.id == wallet_id)
        ) == Decimal("9.00")

    finally:
        locker.rollback()
        contender.rollback()
        locker.close()
        contender.close()


# ---------------------------------------------------------------------
# Ledger failure rollback test
# ---------------------------------------------------------------------


def test_postgres_ledger_failure_rolls_back_purchase_finalization(
    db,
    monkeypatch,
):
    from app.commission import service as commission_service
    from app.commission.service import (
        finalize_confirmed_purchase,
        record_provider_success,
    )
    from app.models.commission import PurchaseCommission
    from app.models.platform_wallet import (
        PlatformTransaction,
        PlatformWallet,
    )
    from app.models.transaction import Transaction

    _, _, tx = _seed_purchase(
        db,
        amount=Decimal("2000.00"),
        category="data",
    )

    _enable_commission(db, category="data")

    def fail_credit(*_args, **_kwargs):
        raise RuntimeError("synthetic ledger posting failure")

    monkeypatch.setattr(
        commission_service,
        "credit_platform_wallet_system",
        fail_credit,
    )

    record_provider_success(
        db,
        purchase_transaction_id=tx.id,
        provider="bigisub",
        provider_reference="SYNTHETIC-PROVIDER-OK",
        service_category="data",
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic ledger posting failure",
    ):
        finalize_confirmed_purchase(
            db,
            purchase_transaction_id=tx.id,
        )

    db.rollback()

    assert db.get(Transaction, tx.id).status == "pending"
    assert db.scalar(
        select(func.count(PurchaseCommission.id))
    ) == 0
    assert db.scalar(
        select(func.count(PlatformTransaction.id))
    ) == 0

    # The platform wallet may be initialized independently of a ledger posting.
    # A failed commission posting must leave its balance unchanged at zero.
    platform_wallet = db.scalar(select(PlatformWallet))

    assert platform_wallet is not None
    assert platform_wallet.balance == Decimal("0.00")


# ---------------------------------------------------------------------
# Insufficient platform funds / refund review test
# ---------------------------------------------------------------------


def test_postgres_insufficient_platform_funds_leave_reversal_for_review(db):
    from app.models.commission import CommissionReversal
    from app.models.platform_wallet import PlatformWallet
    from app.models.transaction import Transaction
    from app.wallet.service import WalletService

    _, wallet, tx = _seed_purchase(
        db,
        amount=Decimal("100.00"),
        category="data",
    )

    _enable_commission(db, category="data")

    commission = _confirm(db, tx, category="data")

    platform = db.scalar(select(PlatformWallet))
    platform.balance = Decimal("0.00")

    db.get(Transaction, tx.id).status = "failed"
    db.commit()

    WalletService.credit(
        db,
        wallet_id=wallet.id,
        amount=Decimal("100.00"),
        reference=f"{tx.reference}-REFUND",
        transaction_type="data_purchase_refund",
    )

    db.commit()

    reversal = db.scalar(
        select(CommissionReversal).where(
            CommissionReversal.commission_id == commission.id
        )
    )

    assert reversal.status == "pending_review"
    assert reversal.platform_transaction_id is None

    assert db.scalar(
        select(PlatformWallet.balance)
    ) == Decimal("0.00")
