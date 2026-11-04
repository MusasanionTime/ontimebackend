from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.wallet.service import WalletService


def test_same_reference_and_payload_returns_existing_transaction():
    wallet_id = uuid4()
    existing = SimpleNamespace(
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        transaction_type="deposit",
        direction="credit",
    )
    db = SimpleNamespace(scalar=lambda _query: existing)

    result = WalletService._existing_reference(
        db,
        reference="monnify-123",
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        transaction_type="deposit",
        direction="credit",
    )

    assert result is existing


def test_reference_reuse_with_different_payload_is_rejected():
    wallet_id = uuid4()
    existing = SimpleNamespace(
        wallet_id=wallet_id,
        amount=Decimal("500.00"),
        transaction_type="deposit",
        direction="credit",
    )
    db = SimpleNamespace(scalar=lambda _query: existing)

    with pytest.raises(HTTPException) as error:
        WalletService._existing_reference(
            db,
            reference="monnify-123",
            wallet_id=wallet_id,
            amount=Decimal("700.00"),
            transaction_type="deposit",
            direction="credit",
        )

    assert error.value.status_code == 409
