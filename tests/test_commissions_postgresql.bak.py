"""PostgreSQL-only integration coverage for commissions.

Set TEST_DATABASE_URL to the dedicated ontime_commission_staging database to
run these tests. Each run migrates and drops its own randomly named schema;
the database's public schema and data are not modified by this test module.
"""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
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

    wallet = Wallet(
        id=uuid.uuid4(),
        user_id=user_id,
        wallet_number=f"IT-{user_id.hex[:20]}",
        currency="NGN",
        balance=Decimal("0.00"),
        status="active",
    )

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

    # Step 1: Insert the user first.
    db.add(user)
    db.flush()

    # Step 2: Insert the wallet after its user exists.
    db.add(wallet)
    db.flush()

    # Step 3: Insert the transaction after its wallet exists.
    db.add(tx)
    db.commit()

    # Refresh persisted objects before returning.
    db.refresh(user)
    db.refresh(wallet)
    db.refresh(tx)

    return user, wallet, tx
