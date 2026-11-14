import hashlib
import hmac
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  # register all tables on shared metadata
from app.api.v1.routes import topify
from app.core.config import settings
from app.database.base import Base
from app.models.topify_account import TopifyAccount
from app.models.topify_webhook_event import TopifyWebhookEvent
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.topify.client import TopifyClient
from app.topify.service import kobo_to_naira, parse_kobo, verify_webhook_signature


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        engine.dispose()


def seed_customer(db):
    user = User(
        id=uuid4(),
        email="ada@example.test",
        phone="08012345678",
        password_hash="unused-test-hash",
        referral_code=f"T{uuid4().hex[:8]}",
        first_name="Ada",
        last_name="Okafor",
        is_active=True,
    )
    wallet = Wallet(
        id=uuid4(),
        user_id=user.id,
        wallet_number=f"W{uuid4().hex[:12]}",
        currency="NGN",
        balance=Decimal("50.00"),
        status="active",
    )
    account = TopifyAccount(
        id=uuid4(),
        user_id=user.id,
        wallet_id=wallet.id,
        request_email=user.email,
        request_name="Ada Okafor",
        request_phone=user.phone,
        customer_code="CUS-ONTIME-1",
        account_number="9012345678",
        account_name="ADA OKAFOR",
        bank_name="Moniepoint MFB",
        bank_code="30901",
        currency="NGN",
        status="active",
        is_sandbox=True,
    )
    db.add_all([user, wallet, account])
    db.commit()
    return user, wallet, account


def payment_payload(reference="TPY-TXN-1", delivery="delivery-1"):
    payload = {
        "event": "charge.success",
        "data": {
            "reference": reference,
            "provider_reference": "MONIEPOINT-SETTLEMENT-1",
            "provider": "moniepoint",
            "amount": 10000,
            "fee": 250,
            "currency": "NGN",
            "status": "success",
            "paid_at": "2026-11-09T12:00:00+01:00",
            "customer": {
                "customer_code": "CUS-ONTIME-1",
                "email": "ada@example.test",
                "name": "Ada Okafor",
            },
            "virtual_account": {
                "provider": "moniepoint",
                "account_number": "9012345678",
                "bank_name": "Moniepoint MFB",
            },
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"test-webhook-secret", raw, hashlib.sha512).hexdigest()
    return raw, signature, payload["data"], delivery


def test_webhook_hmac_uses_raw_body_and_constant_time_signature(monkeypatch):
    monkeypatch.setattr(settings, "TOPIFY_WEBHOOK_SECRET", "test-webhook-secret")
    raw = b'{"event":"charge.success","data":{"amount":10000}}'
    signature = hmac.new(b"test-webhook-secret", raw, hashlib.sha512).hexdigest()
    assert verify_webhook_signature(raw, signature.upper())
    assert not verify_webhook_signature(raw + b" ", signature)
    assert not verify_webhook_signature(raw, None)


@pytest.mark.parametrize("invalid", [True, 10.0, "100", -1, 0])
def test_kobo_parser_rejects_non_integer_or_nonpositive_values(invalid):
    with pytest.raises(ValueError):
        parse_kobo(invalid)


def test_kobo_conversion_is_exact_to_naira():
    assert kobo_to_naira(parse_kobo(250050)) == Decimal("2500.50")
    assert kobo_to_naira(parse_kobo(9750)) == Decimal("97.50")


def test_reservation_request_is_moniepoint_only_and_never_sends_identity(monkeypatch):
    sent = {}

    def fake_request(self, method, path, *, json_body=None):
        sent.update(method=method, path=path, body=json_body)
        return {"status": True, "data": {"customer": {"customer_code": "CUS-1"}}}

    monkeypatch.setattr(settings, "TOPIFY_BASE_URL", "https://apipay.topify.ng")
    monkeypatch.setattr(settings, "TOPIFY_API_KEY", "sk_test_placeholder")
    monkeypatch.setattr(TopifyClient, "_request", fake_request)
    result = TopifyClient().reserve_virtual_account(
        email="ada@example.test",
        name="Ada Okafor",
        phone_number="08012345678",
        business_id="TPYBIZ-APPROVED-TEST",
    )
    assert result["customer"]["customer_code"] == "CUS-1"
    assert sent["method"] == "POST"
    assert sent["path"] == "/api/v1/virtual-accounts/reserve"
    assert sent["body"]["bankCode"] == ["30901"]
    assert set(sent["body"]) == {
        "email",
        "name",
        "phoneNumber",
        "bankCode",
        "businessId",
    }
    assert "bvn" not in sent["body"] and "nin" not in sent["body"]


def test_reserve_endpoint_persists_pending_record_and_reuses_provider_idempotency_tuple(
    db_factory, monkeypatch
):
    db = db_factory()
    user = User(
        id=uuid4(),
        email="new@example.test",
        phone="08099998888",
        password_hash="x",
        referral_code=f"T{uuid4().hex[:8]}",
        first_name="New",
        last_name="Customer",
        is_active=True,
    )
    wallet = Wallet(
        id=uuid4(),
        user_id=user.id,
        wallet_number=f"W{uuid4().hex[:12]}",
        currency="NGN",
        balance=Decimal("0.00"),
        status="active",
    )
    db.add_all([user, wallet])
    db.commit()
    sent = []

    def fake_reserve(self, **kwargs):
        sent.append(kwargs)
        return {
            "customer": {"customer_code": "CUS-NEW"},
            "accounts": [
                {
                    "provider": "moniepoint",
                    "account_number": "9088776655",
                    "account_name": "NEW CUSTOMER",
                    "bank_name": "Moniepoint MFB",
                    "is_active": True,
                    "is_sandbox": True,
                }
            ],
        }

    monkeypatch.setattr(settings, "TOPIFY_ENABLED", True)
    monkeypatch.setattr(settings, "TOPIFY_API_KEY", "sk_test_placeholder")
    monkeypatch.setattr(settings, "TOPIFY_BUSINESS_ID", "approved-test-business")
    monkeypatch.setattr(TopifyClient, "reserve_virtual_account", fake_reserve)
    response = topify.reserve_account(current_user=user, db=db)
    saved = db.scalar(select(TopifyAccount).where(TopifyAccount.user_id == user.id))
    assert response["data"]["account_number"] == "9088776655"
    assert saved.status == "active"
    assert sent == [
        {
            "email": "new@example.test",
            "name": "New Customer",
            "phone_number": "08099998888",
            "business_id": "approved-test-business",
        }
    ]
    db.close()


def test_charge_success_is_verified_and_credits_net_amount_once(db_factory):
    db = db_factory()
    _user, wallet, account = seed_customer(db)
    data = payment_payload()[2]
    verified = {
        "reference": data["reference"],
        "amount": 10000,
        "fee": 250,
        "status": "success",
    }

    result = topify._credit_verified_charge(
        db,
        account=account,
        event_data=data,
        verified=verified,
        delivery_id="delivery-1",
    )
    db.commit()
    assert result == "credited"
    assert wallet.balance == Decimal("147.50")
    transaction = db.scalar(
        select(Transaction).where(Transaction.provider_reference == data["reference"])
    )
    assert transaction.amount == Decimal("97.50")
    assert transaction.provider_metadata["topify"]["amount_kobo"] == 10000
    assert transaction.provider_metadata["topify"]["fee_kobo"] == 250

    duplicate = topify._credit_verified_charge(
        db,
        account=account,
        event_data=data,
        verified=verified,
        delivery_id="delivery-retry",
    )
    db.commit()
    assert duplicate == "duplicate"
    assert wallet.balance == Decimal("147.50")
    assert (
        len(
            db.scalars(
                select(Transaction).where(Transaction.provider == "topify")
            ).all()
        )
        == 1
    )
    db.close()


def test_charge_success_amount_and_fee_mismatches_are_rejected(db_factory):
    db = db_factory()
    _, _, account = seed_customer(db)
    data = payment_payload()[2]
    with pytest.raises(ValueError):
        topify._credit_verified_charge(
            db,
            account=account,
            event_data=data,
            verified={
                "reference": data["reference"],
                "amount": 10001,
                "fee": 250,
                "status": "success",
            },
            delivery_id="delivery-1",
        )
    db.rollback()
    assert (
        db.scalar(select(Transaction).where(Transaction.provider == "topify")) is None
    )
    db.close()


def test_signed_webhook_delivery_and_payment_reference_are_both_idempotent(db_factory):
    db = db_factory()
    user, _wallet, _account = seed_customer(db)
    _, _, data, delivery = payment_payload()
    verified = {
        "reference": data["reference"],
        "amount": 10000,
        "fee": 250,
        "status": "success",
    }
    first = topify._process_webhook_event(
        db,
        delivery_id=delivery,
        event_type="charge.success",
        event_data=data,
        verified=verified,
    )
    repeated = topify._process_webhook_event(
        db,
        delivery_id=delivery,
        event_type="charge.success",
        event_data=data,
        verified=verified,
    )
    changed_delivery = topify._process_webhook_event(
        db,
        delivery_id="delivery-2",
        event_type="charge.success",
        event_data=data,
        verified=verified,
    )
    assert first["status"] == "credited"
    assert repeated["status"] == "already_processed"
    assert changed_delivery["status"] == "duplicate"

    saved_wallet = db.scalar(select(Wallet).where(Wallet.user_id == user.id))
    assert saved_wallet.balance == Decimal("147.50")
    assert (
        db.scalar(
            select(TopifyWebhookEvent).where(TopifyWebhookEvent.delivery_id == delivery)
        )
        is not None
    )
    db.close()


def test_reversal_marks_ledger_only_and_does_not_change_wallet(db_factory):
    db = db_factory()
    _, wallet, account = seed_customer(db)
    data = payment_payload()[2]
    topify._credit_verified_charge(
        db,
        account=account,
        event_data=data,
        verified={
            "reference": data["reference"],
            "amount": 10000,
            "fee": 250,
            "status": "success",
        },
        delivery_id="delivery-1",
    )
    db.commit()
    balance_before = wallet.balance
    status_value = topify._apply_non_credit_event(
        db,
        event_type="transaction.reversed",
        event_data={"reference": data["reference"], "amount": 10000, "currency": "NGN"},
        delivery_id="reversal-1",
    )
    db.commit()
    transaction = db.scalar(
        select(Transaction).where(Transaction.provider_reference == data["reference"])
    )
    assert status_value == "reversed_without_balance_change"
    assert transaction.status == "reversed"
    assert transaction.provider_metadata["topify_reversal"]["balance_adjusted"] is False
    assert wallet.balance == balance_before == Decimal("147.50")
    db.close()


def test_customer_account_lookup_is_scoped_to_owner(db_factory):
    db = db_factory()
    user, _, account = seed_customer(db)
    assert topify._account_view(account)["account_number"] == "9012345678"
    other_user = User(
        id=uuid4(),
        email="other@example.test",
        phone="08000000000",
        password_hash="x",
        referral_code=f"T{uuid4().hex[:8]}",
        first_name="Other",
        last_name="User",
    )
    db.add(other_user)
    db.commit()
    assert (
        db.scalar(select(TopifyAccount).where(TopifyAccount.user_id == other_user.id))
        is None
    )
    assert account.user_id == user.id
    db.close()


def test_transaction_verification_requires_wallet_ownership(db_factory, monkeypatch):
    db = db_factory()
    user, _, account = seed_customer(db)
    data = payment_payload()[2]
    topify._credit_verified_charge(
        db,
        account=account,
        event_data=data,
        verified={
            "reference": data["reference"],
            "amount": 10000,
            "fee": 250,
            "status": "success",
        },
        delivery_id="delivery-1",
    )
    db.commit()
    other_user = User(
        id=uuid4(),
        email="other@example.test",
        phone="08000000000",
        password_hash="unused-test-hash",
        referral_code=f"T{uuid4().hex[:8]}",
        first_name="Other",
        last_name="User",
        is_active=True,
    )
    db.add(other_user)
    db.commit()
    monkeypatch.setattr(settings, "TOPIFY_ENABLED", True)
    monkeypatch.setattr(settings, "TOPIFY_API_KEY", "sk_test_placeholder")
    monkeypatch.setattr(
        TopifyClient,
        "verify_transaction",
        lambda _self, reference: {
            "reference": reference,
            "amount": 10000,
            "fee": 250,
            "status": "success",
        },
    )

    result = topify.verify_my_transaction(data["reference"], current_user=user, db=db)
    assert result["data"]["status"] == "completed"
    with pytest.raises(HTTPException) as error:
        topify.verify_my_transaction(data["reference"], current_user=other_user, db=db)
    assert error.value.status_code == 404
    db.close()


def test_wallet_funded_and_charge_failed_events_never_credit_wallet(db_factory):
    db = db_factory()
    _, wallet, _ = seed_customer(db)
    start_balance = wallet.balance
    funded = topify._process_webhook_event(
        db,
        delivery_id="wallet-funded-1",
        event_type="wallet.funded",
        event_data={
            "reference": "unverified-1",
            "amount": 10000,
            "fee": 250,
            "currency": "NGN",
        },
    )
    failed = topify._process_webhook_event(
        db,
        delivery_id="charge-failed-1",
        event_type="charge.failed",
        event_data={"reference": "failed-1", "amount": 10000, "currency": "NGN"},
    )
    assert funded["status"] == "acknowledged_without_credit"
    assert failed["status"] == "failed"
    assert wallet.balance == start_balance == Decimal("50.00")
    assert (
        db.scalar(select(Transaction).where(Transaction.provider == "topify")) is None
    )
    db.close()
