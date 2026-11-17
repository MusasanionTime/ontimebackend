from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1.routes.admin_commissions import (
    commission_overview,
    commission_summary,
    get_commission,
    list_commissions,
    update_commission_settings,
)
from app.auth.admin import get_current_admin
from app.commission.service import (
    calculate_commission,
    finalize_confirmed_purchase,
    record_provider_success,
    reverse_commission_for_purchase,
)
from app.database.base import Base
from app.models.admin import Admin
from app.models.admin_audit_log import AdminAuditLog
from app.models.commission import CommissionConfiguration, CommissionReversal, PurchaseCommission
from app.models.platform_wallet import PlatformTransaction, PlatformWallet
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.platform_wallet.service import debit_platform_wallet
from app.wallet.service import WalletService


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def seed_purchase(
    db: Session, *, amount=Decimal("100.00"), status="pending",
    category="data", purchase_amount: Decimal | None = None,
):
    user = User(
        id=uuid4(), email=f"customer-{uuid4().hex[:8]}@example.test",
        phone=None, password_hash="test-hash", referral_code=f"T{uuid4().hex[:10]}",
        first_name="Test", last_name="Customer", is_active=True,
    )
    wallet = Wallet(
        id=uuid4(), user_id=user.id, wallet_number=f"W{uuid4().hex[:12]}",
        currency="NGN", balance=Decimal("0.00"), status="active",
    )
    transaction = Transaction(
        id=uuid4(), wallet_id=wallet.id, reference=f"TEST-{uuid4().hex.upper()}",
        transaction_type=f"{category}_purchase", direction="debit", amount=amount,
        balance_before=amount, balance_after=Decimal("0.00"), currency="NGN",
        status=status, provider="bigisub",
        provider_metadata={"commission_purchase_amount": str(purchase_amount if purchase_amount is not None else amount)},
    )
    db.add_all([user, wallet, transaction])
    db.commit()
    return user, wallet, transaction


def enable_commissions(db: Session, *, category="data", value=Decimal("10.000000"), calc_type="percentage"):
    now = datetime.now(timezone.utc) - timedelta(days=1)
    global_config = CommissionConfiguration(
        id=uuid4(), service_key="global", revision=1, is_enabled=True,
        effective_from=now, reason="Test-only enabled fixture",
    )
    service_config = CommissionConfiguration(
        id=uuid4(), service_key=category, revision=1, is_enabled=True,
        calculation_type=calc_type, commission_value=value,
        calculation_basis="customer_purchase_amount", effective_from=now,
        reason="Test-only approved fixture",
    )
    db.add_all([global_config, service_config])
    db.commit()
    return global_config, service_config


def confirm_purchase(db: Session, tx: Transaction, category="data"):
    record_provider_success(
        db,
        purchase_transaction_id=tx.id,
        provider="bigisub",
        provider_reference="PROVIDER-TEST-1",
        service_category=category,
    )
    return finalize_confirmed_purchase(db, purchase_transaction_id=tx.id)


def test_percentage_fixed_and_caps_use_decimal_rounding():
    assert calculate_commission(Decimal("10.05"), "percentage", Decimal("12.5")) == Decimal("1.26")
    assert calculate_commission(Decimal("10.00"), "fixed", Decimal("2.00")) == Decimal("2.00")
    assert calculate_commission(
        Decimal("100.00"), "percentage", Decimal("10"),
        minimum_commission=Decimal("15"), maximum_commission=Decimal("20"),
    ) == Decimal("15.00")


@pytest.mark.parametrize(
    "category,purchase_amount,wallet_debit,rate,expected",
    [
        ("airtime", "1000.00", "1000.00", "2.000000", "20.00"),
        ("data", "2000.00", "2000.00", "2.000000", "40.00"),
        # Electricity can reserve a service charge in addition to the requested amount.
        ("electricity", "5000.00", "5050.00", "1.000000", "50.00"),
        ("result_checker", "1500.00", "1500.00", "2.000000", "30.00"),
    ],
)
def test_proposed_rates_use_customer_purchase_amount(
    session, category, purchase_amount, wallet_debit, rate, expected
):
    _, _, tx = seed_purchase(
        session, category=category, amount=Decimal(wallet_debit),
        purchase_amount=Decimal(purchase_amount),
    )
    enable_commissions(session, category=category, value=Decimal(rate))
    commission = confirm_purchase(session, tx, category=category)
    assert commission.purchase_amount == Decimal(purchase_amount)
    assert commission.commission_amount == Decimal(expected)
    assert commission.calculation_basis == "customer_purchase_amount"


def test_missing_service_rate_posts_no_commission(session):
    _, _, tx = seed_purchase(session, category="airtime", amount=Decimal("1000.00"))
    now = datetime.now(timezone.utc) - timedelta(days=1)
    session.add(CommissionConfiguration(
        id=uuid4(), service_key="global", revision=1, is_enabled=True,
        effective_from=now, reason="Test-only global enable",
    ))
    session.commit()
    assert confirm_purchase(session, tx, category="airtime") is None
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 0


def test_changenow_is_not_an_eligible_commission_category(session):
    _, _, tx = seed_purchase(session, category="changenow", amount=Decimal("1000.00"))
    enable_commissions(session, category="airtime", value=Decimal("2"))
    with pytest.raises(HTTPException) as error:
        confirm_purchase(session, tx, category="changenow")
    assert error.value.status_code == 409
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 0


@pytest.mark.parametrize(
    "amount,kind,value",
    [
        (Decimal("0"), "percentage", Decimal("5")),
        (Decimal("10"), "percentage", Decimal("100.01")),
        (Decimal("10"), "unknown", Decimal("1")),
    ],
)
def test_calculation_rejects_invalid_inputs(amount, kind, value):
    with pytest.raises(ValueError):
        calculate_commission(amount, kind, value)


def test_global_disabled_by_default_posts_no_commission(session):
    user, wallet, tx = seed_purchase(session)
    session.add(CommissionConfiguration(
        id=uuid4(), service_key="global", revision=1, is_enabled=False,
        effective_from=datetime.now(timezone.utc) - timedelta(days=1),
        reason="Disabled default",
    ))
    session.commit()
    assert confirm_purchase(session, tx) is None
    assert session.get(Transaction, tx.id).status == "completed"
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 0
    assert session.scalar(select(func.count(PlatformTransaction.id))) == 0


def test_successful_purchase_posts_platform_wallet_ledger_once(session):
    _, _, tx = seed_purchase(session, amount=Decimal("250.00"))
    enable_commissions(session, value=Decimal("2.5"))
    commission = confirm_purchase(session, tx)
    assert commission.commission_amount == Decimal("6.25")
    assert commission.purchase_amount == Decimal("250.00")
    assert commission.status == "posted"
    ledger = session.get(PlatformTransaction, commission.platform_transaction_id)
    platform = session.get(PlatformWallet, ledger.platform_wallet_id)
    assert ledger.transaction_type == "purchase_commission"
    assert ledger.direction == "credit"
    assert ledger.amount == Decimal("6.25")
    assert platform.balance == Decimal("6.25")

    duplicate = confirm_purchase(session, session.get(Transaction, tx.id))
    assert duplicate.id == commission.id
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 1
    assert session.scalar(select(func.count(PlatformTransaction.id))) == 1


def test_platform_ledger_posting_failure_rolls_back_purchase_finalization(session, monkeypatch):
    _, _, tx = seed_purchase(session, amount=Decimal("2000.00"), category="data")
    enable_commissions(session, category="data", value=Decimal("2"))

    import app.commission.service as commission_service
    from app.api.v1.routes.bigisub import _finalize_confirmed_purchase

    def fail_platform_post(*args, **kwargs):
        raise RuntimeError("Injected platform ledger failure")

    monkeypatch.setattr(commission_service, "credit_platform_wallet_system", fail_platform_post)
    finalized = _finalize_confirmed_purchase(
        session, tx, service_category="data", provider_reference="TEST-PROVIDER-OK"
    )

    assert finalized is False
    assert session.get(Transaction, tx.id).status == "pending"
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 0
    assert session.scalar(select(func.count(PlatformTransaction.id))) == 0
    assert session.scalar(select(func.count(PlatformWallet.id))) == 0


def test_unique_source_constraint_is_final_guard_for_competing_commission_posts(session):
    _, _, tx = seed_purchase(session, amount=Decimal("100.00"))
    _, config = enable_commissions(session)
    commission = confirm_purchase(session, tx)
    session.add(PurchaseCommission(
        id=uuid4(), reference=f"DUP-{uuid4().hex}", customer_id=commission.customer_id,
        source_transaction_id=tx.id, configuration_id=config.id,
        provider="bigisub", service_category="data", purchase_amount=Decimal("100.00"),
        calculation_type="percentage", calculation_value=Decimal("10"),
        calculation_basis="customer_purchase_amount", commission_amount=Decimal("10.00"),
        currency="NGN", status="posted",
    ))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_pending_or_failed_purchase_never_posts_commission(session):
    _, _, pending = seed_purchase(session)
    enable_commissions(session)
    with pytest.raises(HTTPException) as error:
        finalize_confirmed_purchase(session, purchase_transaction_id=pending.id)
    assert error.value.status_code == 409
    pending.status = "failed"
    pending.provider_metadata = {"provider_success_confirmed": True, "commission_service_category": "data"}
    session.commit()
    with pytest.raises(HTTPException) as error:
        finalize_confirmed_purchase(session, purchase_transaction_id=pending.id)
    assert error.value.status_code == 409
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 0


def test_fixed_commission_is_posted_only_for_confirmed_provider_success(session):
    _, _, tx = seed_purchase(session, amount=Decimal("75.00"))
    enable_commissions(session, value=Decimal("1.250000"), calc_type="fixed")
    commission = confirm_purchase(session, tx)
    assert commission.calculation_type == "fixed"
    assert commission.calculation_value == Decimal("1.250000")
    assert commission.commission_amount == Decimal("1.25")


def test_verified_purchase_refund_reverses_commission_idempotently(session):
    _, wallet, tx = seed_purchase(session, amount=Decimal("100.00"))
    enable_commissions(session, value=Decimal("5"))
    commission = confirm_purchase(session, tx)
    tx.status = "failed"
    session.commit()
    refund = WalletService.credit(
        session, wallet_id=wallet.id, amount=Decimal("100.00"),
        reference=f"{tx.reference}-REFUND", transaction_type="data_purchase_refund",
        description="Verified test refund",
    )
    session.commit()
    reversal = session.scalar(select(CommissionReversal).where(CommissionReversal.commission_id == commission.id))
    assert refund.status == "completed"
    assert reversal.status == "completed"
    assert reversal.amount == commission.commission_amount == Decimal("5.00")
    assert session.get(PurchaseCommission, commission.id).status == "reversed"
    ledger = session.get(PlatformTransaction, reversal.platform_transaction_id)
    platform = session.get(PlatformWallet, ledger.platform_wallet_id)
    assert ledger.transaction_type == "purchase_commission_reversal"
    assert ledger.direction == "debit"
    assert platform.balance == Decimal("0.00")

    duplicate = reverse_commission_for_purchase(
        session, purchase_transaction=session.get(Transaction, tx.id),
        refund_reference=f"{tx.reference}-REFUND", reason="Duplicate callback",
    )
    assert duplicate.id == reversal.id
    assert session.scalar(select(func.count(CommissionReversal.id))) == 1


def test_insufficient_platform_balance_creates_review_without_negative_balance(session):
    _, wallet, tx = seed_purchase(session, amount=Decimal("40.00"))
    enable_commissions(session, value=Decimal("10"))
    commission = confirm_purchase(session, tx)
    admin = Admin(id=uuid4(), email="owner@example.test", password_hash="test", role="super_admin")
    session.add(admin)
    session.commit()
    platform = session.scalar(select(PlatformWallet))
    debit_platform_wallet(
        session, admin=admin, amount=platform.balance,
        reference="TEST-SPEND-PLATFORM-FUNDS", transaction_type="admin_adjustment",
    )
    session.commit()
    tx.status = "failed"
    session.commit()
    WalletService.credit(
        session, wallet_id=wallet.id, amount=Decimal("40.00"),
        reference=f"{tx.reference}-REFUND", transaction_type="data_purchase_refund",
        description="Verified test refund",
    )
    session.commit()
    reversal = session.scalar(select(CommissionReversal).where(CommissionReversal.commission_id == commission.id))
    assert reversal.status == "pending_review"
    assert session.scalar(select(PlatformWallet.balance)) == Decimal("0.00")
    assert reversal.platform_transaction_id is None


def test_referral_bonus_is_not_a_purchase_commission(session):
    _, wallet, _ = seed_purchase(session)
    WalletService.credit(
        session, wallet_id=wallet.id, amount=Decimal("3.00"),
        reference="TEST-REFERRAL-BONUS", transaction_type="referral_bonus",
        description="Separate referral reward",
    )
    session.commit()
    assert session.scalar(select(func.count(PurchaseCommission.id))) == 0
    assert session.scalar(select(Transaction.transaction_type).where(Transaction.reference == "TEST-REFERRAL-BONUS")) == "referral_bonus"


def test_standard_admin_cannot_change_commission_configuration(session):
    admin = Admin(id=uuid4(), email="ordinary@example.test", password_hash="test", role="admin")
    session.add(admin)
    session.commit()
    from fastapi import HTTPException
    from app.auth.admin import require_super_admin

    with pytest.raises(HTTPException) as error:
        require_super_admin(admin)
    assert error.value.status_code == 403


def test_only_super_admin_can_enable_and_invalid_configuration_is_rejected(session):
    owner = Admin(id=uuid4(), email="owner2@example.test", password_hash="test", role="super_admin")
    session.add(owner)
    session.commit()
    payload = type("Payload", (), {
        "is_enabled": True, "calculation_type": None, "commission_value": None,
        "calculation_basis": None, "minimum_commission": None, "maximum_commission": None,
        "effective_from": None, "reason": "Attempt to enable without an approved rate",
    })()
    with pytest.raises(HTTPException) as error:
        update_commission_settings("data", payload, None, owner, session)
    assert error.value.status_code == 422


def test_configuration_revision_and_audit_history(session):
    owner = Admin(id=uuid4(), email="owner3@example.test", password_hash="test", role="super_admin")
    session.add(owner)
    session.commit()
    from app.schemas.commission import CommissionConfigurationUpdate
    from starlette.requests import Request

    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    payload = CommissionConfigurationUpdate(
        is_enabled=False,
        reason="Create disabled service configuration for later owner approval",
    )
    first = update_commission_settings("data", payload, request, owner, session)
    assert first.revision == 1 and first.is_enabled is False
    assert session.scalar(select(func.count(AdminAuditLog.id))) == 1
    audit = session.scalar(select(AdminAuditLog))
    assert audit.extra_data["new_values"]["is_enabled"] is False
    assert "old_values" in audit.extra_data


def test_proposed_service_rates_can_be_configured_disabled(session):
    from app.schemas.commission import CommissionConfigurationUpdate
    from starlette.requests import Request

    owner = Admin(id=uuid4(), email="rates-owner@example.test", password_hash="test", role="super_admin")
    now = datetime.now(timezone.utc) - timedelta(days=1)
    session.add_all([
        owner,
        CommissionConfiguration(
            id=uuid4(), service_key="global", revision=1, is_enabled=False,
            effective_from=now, reason="Global switch stays disabled in staging review.",
        ),
    ])
    session.commit()
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    rates = {"airtime": "2", "data": "2", "electricity": "1", "result_checker": "2"}
    for service_key, rate in rates.items():
        result = update_commission_settings(
            service_key,
            CommissionConfigurationUpdate(
                is_enabled=False, calculation_type="percentage",
                commission_value=Decimal(rate),
                calculation_basis="customer_purchase_amount",
                reason="Proposed staging rate; keep disabled.",
            ),
            request, owner, session,
        )
        assert result.is_enabled is False
        assert result.commission_value == Decimal(rate)
    assert session.scalar(select(CommissionConfiguration.is_enabled).where(
        CommissionConfiguration.service_key == "global"
    )) is False


def test_admin_commission_history_detail_and_summaries_are_backend_recorded(session):
    admin = Admin(id=uuid4(), email="reader@example.test", password_hash="test", role="admin")
    session.add(admin)
    session.commit()
    _, _, tx = seed_purchase(session, amount=Decimal("80.00"))
    enable_commissions(session, value=Decimal("2.5"))
    commission = confirm_purchase(session, tx)

    page = list_commissions(service="data", status_filter=None, page=1, page_size=10, admin=admin, db=session)
    detail = get_commission(commission.id, admin=admin, db=session)
    overview = commission_overview(admin=admin, db=session)
    summary = commission_summary(service="data", admin=admin, db=session)

    assert page["total"] == 1
    assert page["items"][0]["reference"] == commission.reference
    assert detail["purchase_reference"] == tx.reference
    assert detail["calculation_basis"] == "customer_purchase_amount"
    assert overview["total_earned"] == Decimal("2.00")
    assert overview["net_total"] == Decimal("2.00")
    assert summary["by_service"][0]["service_category"] == "data"


