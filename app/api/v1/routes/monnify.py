import hashlib
import hmac
import json
import uuid
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import verify_transaction_pin
from app.core.config import settings
from app.database.database import SessionLocal, get_db
from app.models.monnify_account import MonnifyAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.models.withdrawal_bank_account import (
    WithdrawalBankAccount,
)
from app.monnify.service import MonnifyService
from app.schemas.withdrawal import (
    WithdrawalRequest,
    WithdrawalResponse,
)
from app.wallet.service import WalletService


router = APIRouter(
    prefix="/monnify",
    tags=["Monnify"],
)


class ValidateBankAccountRequest(BaseModel):
    account_number: str = Field(
        ...,
        min_length=10,
        max_length=10,
    )

    bank_code: str = Field(
        ...,
        min_length=3,
        max_length=10,
    )


class SaveWithdrawalBankAccountRequest(BaseModel):
    account_number: str = Field(
        ...,
        min_length=10,
        max_length=10,
    )

    bank_code: str = Field(
        ...,
        min_length=3,
        max_length=10,
    )


def verify_signature(
    raw_body: bytes,
    signature: str | None,
) -> bool:
    """
    Verify Monnify webhook signature.

    Sandbox webhook requests may not contain the signature
    header, so sandbox requests are allowed without one.
    """

    if not signature:
        if "sandbox" in settings.MONNIFY_BASE_URL.lower():
            return True

        return False

    expected_signature = hmac.new(
        settings.MONNIFY_SECRET_KEY.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        signature,
    )


@router.post(
    "/validate-bank-account",
)
def validate_bank_account(
    payload: ValidateBankAccountRequest,
):
    service = MonnifyService()

    try:
        result = service.validate_bank_account(
            account_number=payload.account_number,
            bank_code=payload.bank_code,
        )

        return {
            "success": True,
            "message": "Bank account validated successfully.",
            "data": result,
        }

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/withdrawal-bank-account",
)
def save_withdrawal_bank_account(
    payload: SaveWithdrawalBankAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = MonnifyService()

    try:
        verified_account = service.validate_bank_account(
            account_number=payload.account_number,
            bank_code=payload.bank_code,
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    account_number = verified_account.get(
        "accountNumber"
    )

    account_name = verified_account.get(
        "accountName"
    )

    bank_code = verified_account.get(
        "bankCode"
    )

    bank_name = verified_account.get(
        "bankName",
        "",
    )

    currency = verified_account.get(
        "currencyCode",
        "NGN",
    )

    if (
        not account_number
        or not account_name
        or not bank_code
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Monnify returned incomplete "
                "bank account information."
            ),
        )

    existing_account = db.scalar(
        select(WithdrawalBankAccount).where(
            WithdrawalBankAccount.user_id
            == current_user.id,
            WithdrawalBankAccount.account_number
            == account_number,
            WithdrawalBankAccount.bank_code
            == bank_code,
        )
    )

    if existing_account:
        existing_account.account_name = account_name
        existing_account.bank_name = bank_name
        existing_account.status = "active"
        existing_account.currency = currency

        db.commit()
        db.refresh(existing_account)

        return {
            "success": True,
            "message": (
                "Withdrawal bank account "
                "updated successfully."
            ),
            "data": {
                "id": str(existing_account.id),
                "account_number": (
                    existing_account.account_number
                ),
                "account_name": (
                    existing_account.account_name
                ),
                "bank_code": (
                    existing_account.bank_code
                ),
                "bank_name": (
                    existing_account.bank_name
                ),
                "currency": (
                    existing_account.currency
                ),
                "status": (
                    existing_account.status
                ),
            },
        }

    bank_account = WithdrawalBankAccount(
        user_id=current_user.id,
        bank_code=bank_code,
        bank_name=bank_name,
        account_number=account_number,
        account_name=account_name,
        currency=currency,
        status="active",
    )

    db.add(bank_account)
    db.commit()
    db.refresh(bank_account)

    return {
        "success": True,
        "message": (
            "Withdrawal bank account "
            "saved successfully."
        ),
        "data": {
            "id": str(bank_account.id),
            "account_number": (
                bank_account.account_number
            ),
            "account_name": (
                bank_account.account_name
            ),
            "bank_code": (
                bank_account.bank_code
            ),
            "bank_name": (
                bank_account.bank_name
            ),
            "currency": (
                bank_account.currency
            ),
            "status": (
                bank_account.status
            ),
        },
    }


@router.post(
    "/withdraw",
    response_model=WithdrawalResponse,
)
def withdraw(
    payload: WithdrawalRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Initiate a wallet withdrawal through Monnify.

    Flow:

    1. Verify transaction PIN.
    2. Verify the user's saved bank account.
    3. Lock the user's wallet.
    4. Reserve the withdrawal amount.
    5. Commit the reservation.
    6. Submit the transfer to Monnify.
    7. Mark completed when Monnify confirms success.
    8. Keep the transaction pending when the result is uncertain.
    9. Refund the wallet when Monnify explicitly reports
       a failed/reversed/expired transfer.
    """

    # ---------------------------------------------------------
    # 1. Transaction PIN must exist
    # ---------------------------------------------------------

    if not current_user.transaction_pin_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction PIN has not been set.",
        )

    # ---------------------------------------------------------
    # 2. Verify transaction PIN
    # ---------------------------------------------------------

    if not verify_transaction_pin(
        payload.transaction_pin,
        current_user.transaction_pin_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid transaction PIN.",
        )

    # ---------------------------------------------------------
    # 3. Parse saved bank account ID
    # ---------------------------------------------------------

    try:
        bank_account_id = uuid.UUID(
            payload.bank_account_id
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid bank account ID.",
        ) from exc

    # ---------------------------------------------------------
    # 4. Load bank account belonging to current user
    # ---------------------------------------------------------

    bank_account = db.scalar(
        select(WithdrawalBankAccount).where(
            WithdrawalBankAccount.id == bank_account_id,
            WithdrawalBankAccount.user_id
            == current_user.id,
        )
    )

    if not bank_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Withdrawal bank account not found.",
        )

    # ---------------------------------------------------------
    # 5. Verify bank account status
    # ---------------------------------------------------------

    if bank_account.status.lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Withdrawal bank account is not active.",
        )

    # ---------------------------------------------------------
    # 6. Currently support NGN only
    # ---------------------------------------------------------

    if bank_account.currency.upper() != "NGN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only NGN withdrawals are currently supported.",
        )

    # ---------------------------------------------------------
    # 7. Load user's wallet directly
    # ---------------------------------------------------------

    wallet = db.scalar(
        select(Wallet)
        .where(
            Wallet.user_id == current_user.id
        )
        .with_for_update()
    )

    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found.",
        )

    # ---------------------------------------------------------
    # 8. Verify wallet status
    # ---------------------------------------------------------

    if wallet.status.lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet is not active.",
        )

    # ---------------------------------------------------------
    # 9. Verify wallet currency
    # ---------------------------------------------------------

    if (
        wallet.currency.upper()
        != bank_account.currency.upper()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Wallet and withdrawal account "
                "currencies do not match."
            ),
        )

    # ---------------------------------------------------------
    # 10. Convert amount safely
    # ---------------------------------------------------------

    amount = Decimal(
        str(payload.amount)
    ).quantize(
        Decimal("0.01")
    )

    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Withdrawal amount must be "
                "greater than zero."
            ),
        )

    # ---------------------------------------------------------
    # 11. Create unique withdrawal reference
    # ---------------------------------------------------------

    withdrawal_reference = (
        f"GALAXY-WD-{uuid.uuid4().hex[:20].upper()}"
    )

    # ---------------------------------------------------------
    # 12. Create narration
    # ---------------------------------------------------------

    description = (
        payload.narration
        or "Alpa Galaxy wallet withdrawal"
    )

    # ---------------------------------------------------------
    # 13. Reserve wallet funds
    # ---------------------------------------------------------

    transaction = WalletService.reserve_for_withdrawal(
        db,
        wallet_id=wallet.id,
        amount=amount,
        reference=withdrawal_reference,
        provider="monnify",
        description=description,
    )

    # Commit reservation BEFORE calling Monnify.
    db.commit()
    db.refresh(transaction)

    # ---------------------------------------------------------
    # 14. Initiate Monnify transfer
    # ---------------------------------------------------------

    service = MonnifyService()

    try:
        transfer = service.initiate_single_transfer(
            amount=float(amount),
            reference=withdrawal_reference,
            narration=description,
            destination_bank_code=(
                bank_account.bank_code
            ),
            destination_account_number=(
                bank_account.account_number
            ),
            destination_account_name=(
                bank_account.account_name
            ),
            currency=bank_account.currency,
            async_transfer=True,
        )

    except RuntimeError as exc:
        # -----------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT refund here.
        #
        # A timeout/network error does not prove that Monnify
        # rejected the transfer. Monnify may have accepted it
        # while the response was lost.
        #
        # The transaction remains pending and must be checked
        # using Monnify transfer status reconciliation.
        # -----------------------------------------------------

        transaction.status = "pending"

        db.commit()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Withdrawal could not be confirmed immediately. "
                "The transaction remains pending while it is "
                "being reconciled. Do not submit the withdrawal "
                "again."
            ),
        ) from exc

    # ---------------------------------------------------------
    # 15. Save Monnify provider reference
    # ---------------------------------------------------------

    provider_reference = (
        transfer.get("reference")
        or transfer.get("transactionReference")
        or transfer.get("paymentReference")
    )

    if provider_reference:
        transaction.provider_reference = (
            provider_reference
        )

    # ---------------------------------------------------------
    # 16. Read Monnify transfer status
    # ---------------------------------------------------------

    transfer_status = str(
        transfer.get(
            "status",
            "PENDING",
        )
    ).upper()

    # ---------------------------------------------------------
    # 17. Successful transfer
    # ---------------------------------------------------------

    if transfer_status in {
        "SUCCESS",
        "COMPLETED",
    }:
        transaction.status = "completed"

        message = (
            "Withdrawal completed successfully."
        )

    # ---------------------------------------------------------
    # 18. Confirmed failed/reversed/expired transfer
    # ---------------------------------------------------------

    elif transfer_status in {
        "FAILED",
        "REVERSED",
        "EXPIRED",
    }:
        # The response explicitly reports that the transfer
        # was unsuccessful, so the reserved wallet amount can
        # safely be returned.
        transaction.status = (
            "reversed"
            if transfer_status == "REVERSED"
            else "failed"
        )

        refund_transaction = (
            WalletService.refund_withdrawal(
                db,
                transaction=transaction,
                description=(
                    "Withdrawal amount refunded after "
                    f"Monnify transfer status: "
                    f"{transfer_status}."
                ),
            )
        )

        db.commit()

        db.refresh(transaction)
        db.refresh(refund_transaction)

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Monnify reported that the withdrawal "
                "was unsuccessful. The reserved wallet "
                "amount has been refunded."
            ),
        )

    # ---------------------------------------------------------
    # 19. Pending / processing / authorization
    # ---------------------------------------------------------

    else:
        transaction.status = "pending"

        message = (
            "Withdrawal submitted and is pending."
        )

    # ---------------------------------------------------------
    # 20. Save final transaction state
    # ---------------------------------------------------------

    db.commit()
    db.refresh(transaction)

    # ---------------------------------------------------------
    # 21. Return safe response
    # ---------------------------------------------------------

    return WithdrawalResponse(
        success=True,
        message=message,
        data={
            "transaction_id": str(
                transaction.id
            ),
            "reference": transaction.reference,
            "amount": str(
                transaction.amount
            ),
            "currency": transaction.currency,
            "status": transaction.status,
            "provider": transaction.provider,
            "provider_reference": (
                transaction.provider_reference
            ),
            "destination_account_name": (
                bank_account.account_name
            ),
            "destination_account_number": (
                bank_account.account_number[-4:]
            ),
        },
    )


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
)
async def monnify_webhook(
    request: Request,
    monnify_signature: str | None = Header(
        default=None,
        alias="monnify-signature",
    ),
):
    raw_body = await request.body()

    if not verify_signature(
        raw_body,
        monnify_signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid Monnify webhook "
                "signature."
            ),
        )

    try:
        payload = json.loads(
            raw_body
        )

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload.",
        )

    event_type = payload.get(
        "eventType"
    )

    if event_type != "SUCCESSFUL_TRANSACTION":
        return {
            "status": "ignored",
            "message": "Event type not handled.",
        }

    event_data = payload.get(
        "eventData"
    ) or {}

    product = event_data.get(
        "product"
    ) or {}

    if product.get(
        "type"
    ) != "RESERVED_ACCOUNT":
        return {
            "status": "ignored",
            "message": (
                "Transaction is not for "
                "a reserved account."
            ),
        }

    if event_data.get(
        "paymentStatus"
    ) != "PAID":
        return {
            "status": "ignored",
            "message": (
                "Payment is not completed."
            ),
        }

    account_reference = product.get(
        "reference"
    )

    transaction_reference = event_data.get(
        "transactionReference"
    )

    amount_paid = event_data.get(
        "amountPaid"
    )

    currency = event_data.get(
        "currency",
        "NGN",
    )

    if not account_reference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing reserved account "
                "reference."
            ),
        )

    if not transaction_reference:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing transaction "
                "reference."
            ),
        )

    if amount_paid is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Missing payment amount."
            ),
        )

    amount = Decimal(
        str(amount_paid)
    )

    if amount <= Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payment amount.",
        )

    db: Session = SessionLocal()

    try:
        existing_transaction = db.scalar(
            select(Transaction).where(
                Transaction.reference
                == transaction_reference
            )
        )

        if existing_transaction:
            return {
                "status": "already_processed",
                "transaction_id": str(
                    existing_transaction.id
                ),
            }

        account = db.scalar(
            select(MonnifyAccount).where(
                MonnifyAccount.account_reference
                == account_reference
            )
        )

        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Monnify reserved account "
                    "not found."
                ),
            )

        if account.status.upper() != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Monnify account is not active."
                ),
            )

        if account.currency != currency:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Currency mismatch.",
            )

        transaction = WalletService.credit(
            db,
            wallet_id=account.wallet_id,
            amount=amount,
            reference=transaction_reference,
            transaction_type="deposit",
            provider="monnify",
            provider_reference=event_data.get(
                "paymentReference"
            ),
            description=(
                event_data.get(
                    "paymentDescription"
                )
                or "Monnify bank transfer deposit"
            ),
        )

        db.commit()
        db.refresh(transaction)

        return {
            "status": "processed",
            "transaction_id": str(
                transaction.id
            ),
            "wallet_id": str(
                account.wallet_id
            ),
            "amount": str(amount),
            "currency": currency,
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Unable to process "
                "Monnify webhook."
            ),
        )

    finally:
        db.close()
@router.get(
    "/banks",
)
def get_banks():
    """
    Retrieve banks supported by Monnify.

    The bank list is fetched from Monnify dynamically.
    Flutter should not maintain a hardcoded bank list.
    """

    service = MonnifyService()

    try:
        banks = service.get_banks()

        return {
            "success": True,
            "message": "Banks retrieved successfully.",
            "data": banks,
        }

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc        