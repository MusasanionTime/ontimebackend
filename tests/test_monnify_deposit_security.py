import hashlib
import hmac
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.routes.monnify import (
    _reserved_transaction_matches,
    verify_signature,
)
from app.api.v1.routes.monnify_deposits import valid_webhook_signature
from app.core.config import settings


def test_monnify_webhook_hmac_sha512_accepts_exact_raw_body():
    body = b'{"eventType":"SUCCESSFUL_TRANSACTION","eventData":{}}'
    secret = "test-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    assert valid_webhook_signature(body, signature, secret)


def test_monnify_webhook_hmac_sha512_rejects_tampered_body():
    body = b'{"eventType":"SUCCESSFUL_TRANSACTION","eventData":{}}'
    secret = "test-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()

    assert not valid_webhook_signature(body + b" ", signature, secret)
    assert not valid_webhook_signature(body, signature, "wrong-secret")


def test_both_webhooks_only_allow_unsigned_debug_sandbox(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "MONNIFY_BASE_URL", "https://sandbox.monnify.com")
    assert verify_signature(b"{}", None)

    monkeypatch.setattr(settings, "DEBUG", False)
    assert not verify_signature(b"{}", None)

    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "MONNIFY_BASE_URL", "https://api.monnify.com")
    assert not verify_signature(b"{}", None)


def test_reserved_deposit_duplicate_must_match_all_payment_fields():
    wallet_id = uuid4()
    transaction = SimpleNamespace(
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        currency="NGN",
        transaction_type="deposit",
        direction="credit",
        provider="monnify",
    )

    assert _reserved_transaction_matches(
        transaction,
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        currency="ngn",
    )
    for change in (
        {"wallet_id": uuid4()},
        {"amount": Decimal("501.00")},
        {"currency": "USD"},
        {"transaction_type": "withdrawal"},
        {"direction": "debit"},
        {"provider": "other"},
    ):
        original = vars(transaction).copy()
        vars(transaction).update(change)
        assert not _reserved_transaction_matches(
            transaction,
            wallet_id=wallet_id,
            amount=Decimal("500.00"),
            currency="NGN",
        )
        vars(transaction).clear()
        vars(transaction).update(original)


def test_invoice_verification_rejects_reference_amount_and_currency_mismatch():
    from app.api.v1.routes.monnify_deposits import credit_verified_deposit

    tx = SimpleNamespace(
        reference="ONTIME-DEP-1",
        wallet_id=uuid4(),
        status="pending",
        amount=Decimal("500.00"),
        currency="NGN",
        provider="monnify",
        provider_metadata={},
    )
    good = {
        "paymentStatus": "PAID",
        "paymentReference": "ONTIME-DEP-1",
        "amountPaid": "500.00",
        "totalPayable": "500.00",
        "amount": "500.00",
        "currencyCode": "NGN",
    }

    for data in (
        {**good, "paymentReference": "ONTIME-DEP-OTHER"},
        {**good, "amountPaid": "499.00", "totalPayable": "499.00"},
        {**good, "currencyCode": "USD"},
    ):
        db = SimpleNamespace(scalar=lambda *_args, **_kwargs: tx)
        with pytest.raises(HTTPException):
            credit_verified_deposit(
                db,
                payment_reference="ONTIME-DEP-1",
                provider_data=data,
            )


def _invoice_data():
    return {
        "paymentStatus": "PAID",
        "paymentReference": "ONTIME-DEP-1",
        "amountPaid": "500.00",
        "totalPayable": "500.00",
        "amount": "500.00",
        "currencyCode": "NGN",
        "transactionReference": "provider-tx-1",
    }


def test_invoice_deposit_credit_is_completed_once_and_rewards_in_same_transaction(monkeypatch):
    from app.api.v1.routes import monnify_deposits as deposits

    tx = SimpleNamespace(
        reference="ONTIME-DEP-1",
        wallet_id=uuid4(),
        status="pending",
        amount=Decimal("500.00"),
        currency="NGN",
        provider="monnify",
        provider_metadata={},
        balance_before=None,
        balance_after=None,
    )
    wallet = SimpleNamespace(
        id=tx.wallet_id,
        user_id=uuid4(),
        status="active",
        balance=Decimal("25.00"),
    )

    class FakeDB:
        def __init__(self):
            self.rows = [tx, wallet]
            self.commits = 0

        def scalar(self, *_args, **_kwargs):
            return self.rows.pop(0)

        def commit(self):
            self.commits += 1

    db = FakeDB()
    rewarded = []
    monkeypatch.setattr(
        deposits,
        "maybe_reward_first_qualifying_credit",
        lambda *_args, **kwargs: rewarded.append(kwargs),
    )
    result = deposits.credit_verified_deposit(
        db,
        payment_reference=tx.reference,
        provider_data=_invoice_data(),
    )
    assert result["status"] == "completed"
    assert wallet.balance == Decimal("525.00")
    assert tx.status == "completed"
    assert db.commits == 1
    assert len(rewarded) == 1

    db.rows = [tx]
    duplicate = deposits.credit_verified_deposit(
        db,
        payment_reference=tx.reference,
        provider_data=_invoice_data(),
    )
    assert duplicate["status"] == "already_processed"
    assert wallet.balance == Decimal("525.00")
    assert db.commits == 1
    assert len(rewarded) == 1


def test_invoice_referral_failure_rolls_back_wallet_and_transaction(monkeypatch):
    from app.api.v1.routes import monnify_deposits as deposits

    tx = SimpleNamespace(
        reference="ONTIME-DEP-1",
        wallet_id=uuid4(),
        status="pending",
        amount=Decimal("500.00"),
        currency="NGN",
        provider="monnify",
        provider_metadata={},
        balance_before=None,
        balance_after=None,
    )
    wallet = SimpleNamespace(
        id=tx.wallet_id,
        user_id=uuid4(),
        status="active",
        balance=Decimal("25.00"),
    )

    class FakeDB:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0
            self.rows = [tx, wallet]

        def scalar(self, *_args, **_kwargs):
            return self.rows.pop(0)

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1
            tx.status = "pending"
            tx.balance_before = None
            tx.balance_after = None
            wallet.balance = Decimal("25.00")

        def close(self):
            pass

    db = FakeDB()
    monkeypatch.setattr(
        deposits,
        "maybe_reward_first_qualifying_credit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("reward failed")),
    )
    with pytest.raises(RuntimeError):
        try:
            deposits.credit_verified_deposit(
                db,
                payment_reference=tx.reference,
                provider_data=_invoice_data(),
            )
        except Exception:
            db.rollback()
            raise
    assert db.commits == 0
    assert db.rollbacks == 1
    assert tx.status == "pending"
    assert wallet.balance == Decimal("25.00")


def test_reserved_concurrent_duplicate_is_acknowledged_after_unique_conflict():
    from app.api.v1.routes.monnify import _resolve_reserved_duplicate

    wallet_id = uuid4()
    tx = SimpleNamespace(
        id=uuid4(),
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        currency="NGN",
        transaction_type="deposit",
        direction="credit",
        provider="monnify",
    )

    class FakeDB:
        def scalar(self, *_args, **_kwargs):
            return tx

    result = _resolve_reserved_duplicate(
        FakeDB(),
        reference="payment-1",
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        currency="NGN",
    )
    assert result["status"] == "already_processed"


def test_referral_reward_is_recorded_once_for_first_qualifying_credit():
    from app.referral.service import maybe_reward_first_qualifying_credit

    referral = SimpleNamespace(
        referred_user_id=uuid4(),
        referrer_user_id=uuid4(),
        reward_status="pending",
        reward_amount=Decimal("0.00"),
        reward_transaction_reference=None,
        rewarded_at=None,
    )
    settings_row = SimpleNamespace(
        is_enabled=True,
        reward_on_first_transaction=True,
        min_qualifying_amount=Decimal("100.00"),
        reward_type="fixed",
        reward_amount=Decimal("50.00"),
    )
    referrer_wallet = SimpleNamespace(
        id=uuid4(),
        user_id=referral.referrer_user_id,
        balance=Decimal("10.00"),
        status="active",
        currency="NGN",
    )

    class FakeDB:
        def __init__(self):
            self.added = []

        def get(self, _model, _key):
            return settings_row

        def scalar(self, *_args, **_kwargs):
            if referral.reward_status != "pending":
                return None
            # The pending-referral query runs before wallet lookup.
            if not hasattr(self, "found_referral"):
                self.found_referral = True
                return referral
            return referrer_wallet

        def add(self, row):
            self.added.append(row)

        def flush(self):
            pass

    db = FakeDB()
    reward = maybe_reward_first_qualifying_credit(
        db,
        referred_user_id=referral.referred_user_id,
        credited_amount=Decimal("500.00"),
        transaction_type="deposit",
    )
    assert reward is referral
    assert referral.reward_status == "rewarded"
    assert referrer_wallet.balance == Decimal("60.00")
    assert referral.reward_transaction_reference
    assert len(db.added) == 2

    assert maybe_reward_first_qualifying_credit(
        db,
        referred_user_id=referral.referred_user_id,
        credited_amount=Decimal("500.00"),
        transaction_type="deposit",
    ) is None
    assert referrer_wallet.balance == Decimal("60.00")
    assert len(db.added) == 2
