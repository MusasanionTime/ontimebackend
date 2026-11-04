import uuid
import logging

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import verify_transaction_pin
from app.core.config import settings
from app.database.database import get_db
from app.models.wallet import Wallet
from app.wallet.service import WalletService
from app.bigisub.service import BigisubService


router = APIRouter(prefix="/bigisub", tags=["Bigisub"])

logger = logging.getLogger(__name__)


def get_bigisub_service() -> BigisubService:
    return BigisubService()

# ============================================================
# REQUEST MODELS
# ============================================================

class BigisubLoginRequest(BaseModel):
    email_or_username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AirtimePurchaseRequest(BaseModel):
    network: int
    phone_number: str = Field(..., min_length=5)
    amount: str
    airtime_type: str = "vtu"
    pin: str = Field(..., min_length=4, max_length=4)


class DataPurchaseRequest(BaseModel):
    network: int = Field(..., ge=1)
    plan: int = Field(..., ge=1)
    phone_number: str = Field(..., min_length=10, max_length=15)
    transaction_pin: str = Field(
        ..., min_length=4, max_length=4, pattern=r"^\d{4}$"
    )
    ported_number: bool = False


class ElectricityMeterVerificationRequest(BaseModel):
    company: str = Field(..., min_length=2, max_length=50)
    meter_no: str = Field(..., min_length=5, max_length=50)
    meter_type: str = Field(..., pattern=r"^(prepaid|postpaid)$")


class ElectricityPurchaseRequest(BaseModel):
    company: str = Field(..., min_length=2, max_length=50)
    meter_no: str = Field(..., min_length=5, max_length=50)
    meter_type: str = Field(..., pattern=r"^(prepaid|postpaid)$")
    phone_number: str = Field(..., min_length=10, max_length=15)
    amount: str = Field(..., min_length=1)
    transaction_pin: str = Field(
        ..., min_length=4, max_length=4, pattern=r"^\d{4}$"
    )


class ResultCheckerPurchaseRequest(BaseModel):
    exam: str = Field(..., min_length=3, max_length=20)
    quantity: int = Field(default=1, ge=1, le=20)
    transaction_pin: str = Field(
        ..., min_length=4, max_length=4, pattern=r"^\d{4}$"
    )


# ============================================================
# COMMON HELPERS
# ============================================================

def _verify_transaction_pin(current_user, pin: str):
    if not current_user.transaction_pin_hash:
        raise HTTPException(
            status_code=400,
            detail="Transaction PIN has not been set.",
        )

    if not verify_transaction_pin(pin, current_user.transaction_pin_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid transaction PIN.",
        )


def _get_active_ngn_wallet(db: Session, user_id):
    wallet = db.scalar(
        select(Wallet)
        .where(Wallet.user_id == user_id)
        .with_for_update()
    )

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found.")

    if str(wallet.status).lower() != "active":
        raise HTTPException(status_code=400, detail="Wallet is not active.")

    if str(wallet.currency).upper() != "NGN":
        raise HTTPException(
            status_code=400,
            detail="This purchase requires an NGN wallet.",
        )

    return wallet


def _provider_response(provider_result):
    if not isinstance(provider_result, dict):
        provider_result = {}

    data = provider_result.get("data")
    if not isinstance(data, dict):
        data = {}

    status = str(
        data.get("status") or provider_result.get("status") or ""
    ).strip().lower()

    provider_reference = (
        str(
            data.get("transaction_id")
            or data.get("reference")
            or ""
        ).strip()
        or None
    )

    return provider_result, data, status, provider_reference


# ============================================================
# BIGISUB LOGIN
# ============================================================

@router.post("/login")
def bigisub_login(
    payload: BigisubLoginRequest,
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.login(
            email_or_username=payload.email_or_username,
            password=payload.password,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# BIGISUB WALLET BALANCE
# ============================================================

@router.get("/wallet/balance")
def get_wallet_balance(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_wallet_balance()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# AIRTIME
# ============================================================

@router.post("/airtime/purchase")
def purchase_airtime(
    payload: AirtimePurchaseRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: BigisubService = Depends(get_bigisub_service),
):
    """
    Purchase airtime through BigiSub.

    Customer transaction PIN:
        Verified locally.

    BigiSub provider PIN:
        Loaded securely from backend configuration.

    Wallet:
        Funds are reserved before contacting BigiSub.
        Uncertain provider outcomes remain pending.
        Refunds occur only after explicit provider rejection.
    """

    # 1. Validate amount
    try:
        amount = Decimal(str(payload.amount)).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid airtime amount.",
        ) from exc

    if not amount.is_finite() or amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Airtime amount must be greater than zero.",
        )

    # 2. Validate airtime type
    airtime_type = payload.airtime_type.strip().lower()

    if airtime_type != "vtu":
        raise HTTPException(
            status_code=400,
            detail="Only VTU airtime is supported.",
        )

    # 3. Validate phone number
    phone_number = payload.phone_number.strip()

    if not phone_number.isdigit() or len(phone_number) not in (10, 11):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid Nigerian phone number.",
        )

    # 4. Verify customer's transaction PIN
    if not current_user.transaction_pin_hash:
        raise HTTPException(
            status_code=400,
            detail="Please set your transaction PIN first.",
        )

    if not verify_transaction_pin(
        payload.pin,
        current_user.transaction_pin_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect transaction PIN.",
        )

    # 5. Verify BigiSub configuration
    provider_pin = getattr(
        settings,
        "BIGISUB_PROVIDER_PIN",
        None,
    )

    if not provider_pin or not provider_pin.strip():
        raise HTTPException(
            status_code=503,
            detail="Airtime service is currently unavailable.",
        )

    # 6. Get and lock customer's active NGN wallet
    try:
        wallet = _get_active_ngn_wallet(
            db,
            current_user.id,
        )
    except HTTPException:
        raise

    # 7. Generate transaction reference
    reference = (
        f"ONTIME-AIRTIME-{uuid.uuid4().hex[:20].upper()}"
    )

    # 8. Reserve funds
    try:
        transaction = WalletService.reserve_for_withdrawal(
            db,
            wallet_id=wallet.id,
            amount=amount,
            reference=reference,
            provider="bigisub",
            description=(
                f"VTU airtime purchase to {phone_number}"
            ),
        )

        transaction.transaction_type = "airtime_purchase"

        db.commit()
        db.refresh(transaction)

    except HTTPException:
        db.rollback()
        raise

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Unable to reserve funds for airtime purchase."
        )

        raise HTTPException(
            status_code=400,
            detail="Unable to reserve wallet funds.",
        ) from exc

    # 9. Contact BigiSub exactly once
    try:
        provider_result = service.purchase_airtime(
            network=payload.network,
            phone_number=phone_number,
            amount=format(amount, ".2f"),
            airtime_type=airtime_type,
        )

    except Exception:
        logger.exception(
            "Airtime provider outcome uncertain. Reference: %s",
            reference,
        )

        try:
            db.refresh(transaction)
            transaction.status = "pending"
            transaction.description = (
                (transaction.description or "")
                + " | Provider outcome uncertain; reconciliation required."
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Could not update uncertain airtime transaction: %s",
                reference,
            )

        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "amount": str(amount),
            "phone_number": phone_number,
            "message": (
                "Your airtime purchase is being verified. "
                "Do not submit the transaction again until its status is confirmed."
            ),
        }

    # 10. Interpret provider response
    if not isinstance(provider_result, dict):
        transaction.status = "pending"
        db.commit()

        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "message": (
                "Provider returned an unexpected response. "
                "Transaction requires reconciliation."
            ),
        }

    provider_data = provider_result.get("data")

    if not isinstance(provider_data, dict):
        provider_data = {}

    provider_status = str(
        provider_data.get("status")
        or provider_result.get("status")
        or ""
    ).strip().lower()

    provider_reference = (
        provider_data.get("transaction_id")
        or provider_data.get("reference")
        or provider_result.get("transaction_id")
        or provider_result.get("reference")
    )

    provider_success = provider_result.get("success") is True

    if provider_reference:
        transaction.provider_reference = str(provider_reference)

    # 11. Confirmed success
    if provider_success and provider_status in {
        "success",
        "successful",
        "completed",
    }:
        transaction.status = "completed"
        db.commit()
        db.refresh(transaction)

        return {
            "success": True,
            "status": "successful",
            "reference": reference,
            "provider_reference": provider_reference,
            "amount": str(amount),
            "phone_number": phone_number,
            "message": provider_result.get(
                "message",
                "Airtime purchased successfully.",
            ),
            "data": provider_data,
        }

    # 12. Pending provider response
    if provider_status in {
        "pending",
        "processing",
    } or (provider_success and not provider_status):

        transaction.status = "pending"
        db.commit()

        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "provider_reference": provider_reference,
            "amount": str(amount),
            "message": (
                "Your airtime purchase is being processed. "
                "Please do not retry yet."
            ),
        }

    # 13. Refund only on explicit rejection
    explicitly_rejected = (
        provider_result.get("success") is False
        and provider_status in {
            "failed",
            "failure",
            "rejected",
            "declined",
        }
    )

    if explicitly_rejected:
        try:
            WalletService.credit(
                db,
                wallet_id=wallet.id,
                amount=amount,
                reference=f"{reference}-REFUND",
                transaction_type="airtime_purchase_refund",
                provider="bigisub",
                provider_reference=(
                    str(provider_reference)
                    if provider_reference
                    else None
                ),
                description=(
                    f"Refund for rejected airtime purchase {reference}"
                ),
            )

            transaction.status = "failed"

            db.commit()
            db.refresh(transaction)

        except Exception as exc:
            db.rollback()

            logger.exception(
                "Airtime refund failed. Reference: %s",
                reference,
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    "Airtime was rejected, but the refund "
                    "could not be confirmed. Contact support."
                ),
            ) from exc

        raise HTTPException(
            status_code=400,
            detail=provider_result.get(
                "message",
                "Airtime purchase rejected. Refund recorded.",
            ),
        )

    # 14. Unknown response: retain pending status
    transaction.status = "pending"
    transaction.description = (
        (transaction.description or "")
        + " | Unrecognized provider response; reconciliation required."
    )

    db.commit()

    return {
        "success": True,
        "status": "pending",
        "reference": reference,
        "provider_reference": provider_reference,
        "amount": str(amount),
        "message": (
            "Provider outcome could not be confirmed. "
            "Do not retry until reconciliation."
        ),
    }
# ============================================================
# DATA PLANS
# ============================================================

@router.get("/data/plans")
def get_data_plans(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_data_plans()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# DATA PURCHASE
# ============================================================

@router.post("/data/purchase")
def purchase_data(
    payload: DataPurchaseRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: BigisubService = Depends(get_bigisub_service),
):
    if (
        not settings.BIGISUB_PROVIDER_PIN.strip()
        or not settings.BIGISUB_DATA_PURCHASE_PATH.strip()
    ):
        raise HTTPException(
            status_code=503,
            detail="Data purchases are not enabled. Configure BigiSub settings.",
        )

    _verify_transaction_pin(current_user, payload.transaction_pin)

    try:
        catalogue = service.get_data_plans()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to verify the data plan price with BigiSub.",
        ) from exc

    rows = catalogue.get("data", []) if isinstance(catalogue, dict) else catalogue
    if isinstance(rows, dict):
        rows = rows.get("plans", rows.get("results", []))

    if not isinstance(rows, list):
        raise HTTPException(status_code=502, detail="Invalid data catalogue.")

    selected = next(
        (
            row for row in rows
            if isinstance(row, dict)
            and str(row.get("id", row.get("plan", ""))) == str(payload.plan)
            and str(row.get("network", "")) == str(payload.network)
        ),
        None,
    )

    if not selected:
        raise HTTPException(status_code=400, detail="Selected data plan unavailable.")

    if str(selected.get("plan_disabled", "false")).lower() == "true":
        raise HTTPException(status_code=400, detail="Selected data plan is disabled.")

    try:
        amount = Decimal(
            str(selected.get("plan_amount", selected.get("amount")))
        ).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Invalid data plan price.") from exc

    if not amount.is_finite() or amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid data plan price.")

    wallet = _get_active_ngn_wallet(db, current_user.id)
    reference = f"ONTIME-DATA-{uuid.uuid4().hex[:20].upper()}"

    transaction = WalletService.reserve_for_withdrawal(
        db,
        wallet_id=wallet.id,
        amount=amount,
        reference=reference,
        provider="bigisub",
        description=f"Data purchase to {payload.phone_number}, plan {payload.plan}",
    )
    transaction.transaction_type = "data_purchase"
    db.commit()
    db.refresh(transaction)

    try:
        result = service.purchase_data(
            network=payload.network,
            plan=payload.plan,
            phone_number=payload.phone_number,
            ported_number=payload.ported_number,
        )
    except Exception:
        db.refresh(transaction)
        transaction.status = "pending"
        transaction.description = (
            (transaction.description or "")
            + " | Provider outcome uncertain; reconciliation required."
        )
        db.commit()
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "message": "Purchase status is being verified. Do not retry yet.",
        }

    result, data, status, provider_reference = _provider_response(result)
    success = result.get("success") is True

    if success and status in {"successful", "success", "completed"}:
        transaction.status = "completed"
        transaction.provider_reference = provider_reference
        db.commit()
        return {
            "success": True,
            "status": "successful",
            "reference": reference,
            "data": data,
            "message": result.get("message", "Data purchase successful."),
        }

    if status in {"pending", "processing"} or (success and not status):
        transaction.status = "pending"
        transaction.provider_reference = provider_reference
        db.commit()
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "data": data,
            "message": "Provider is processing this purchase. Do not retry yet.",
        }

    rejected = (
        result.get("success") is False
        and status in {"failed", "failure", "rejected", "declined"}
    )

    if not rejected:
        transaction.status = "pending"
        transaction.provider_reference = provider_reference
        transaction.description = (
            (transaction.description or "")
            + " | Unrecognized provider response; reconciliation required."
        )
        db.commit()
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "message": "Provider outcome is unconfirmed. Do not retry yet.",
        }

    try:
        WalletService.credit(
            db,
            wallet_id=wallet.id,
            amount=amount,
            reference=f"{reference}-REFUND",
            transaction_type="data_purchase_refund",
            provider="bigisub",
            provider_reference=provider_reference,
            description=f"Refund for rejected data purchase {reference}",
        )
        transaction.status = "failed"
        transaction.provider_reference = provider_reference
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Purchase rejected but refund could not be confirmed. Contact support.",
        ) from exc

    raise HTTPException(
        status_code=400,
        detail=result.get("message", "BigiSub rejected the data purchase; refund recorded."),
    )


# ============================================================
# CABLE TV
# ============================================================

@router.get("/cable/plans")
def get_cable_plans(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_cable_plans()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# RECHARGE PIN
# ============================================================

@router.get("/recharge-pin/plans")
def get_recharge_pin_plans(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_recharge_pin_plans()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# RESULT CHECKER PRICES
# ============================================================

@router.get("/result-checker/prices")
def get_result_checker_prices(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_result_checker_prices()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# RESULT CHECKER PURCHASE
# ============================================================

@router.post("/result-checker/purchase")
def purchase_result_checker(
    payload: ResultCheckerPurchaseRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: BigisubService = Depends(get_bigisub_service),
):
    """Purchase result checker PINs using the customer's wallet.

    An uncertain provider response remains pending. Never retry automatically.
    """

    if not settings.BIGISUB_PROVIDER_PIN.strip():
        raise HTTPException(
            status_code=503,
            detail="Result Checker purchases are not enabled. Configure BIGISUB_PROVIDER_PIN.",
        )

    exam = payload.exam.strip().upper()
    if exam not in {"WAEC", "NECO", "NABTEB"}:
        raise HTTPException(
            status_code=400,
            detail="Exam must be WAEC, NECO, or NABTEB.",
        )

    if not 1 <= payload.quantity <= 20:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be between 1 and 20.",
        )

    _verify_transaction_pin(current_user, payload.transaction_pin)

    # Fetch the actual current provider price.
    try:
        catalogue = service.get_result_checker_prices()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve Result Checker prices from BigiSub.",
        ) from exc

    if not isinstance(catalogue, dict):
        raise HTTPException(
            status_code=502,
            detail="BigiSub returned an invalid Result Checker catalogue.",
        )

    catalogue_data = catalogue.get("data")
    prices = (
        catalogue_data.get("prices")
        if isinstance(catalogue_data, dict)
        else None
    )

    if not isinstance(prices, list):
        raise HTTPException(
            status_code=502,
            detail="BigiSub returned an unrecognized Result Checker price list.",
        )

    selected = next(
        (
            row for row in prices
            if isinstance(row, dict)
            and (
                str(row.get("exam_type", "")).strip().upper() == exam
                or str(row.get("code", "")).strip().upper() == exam
            )
        ),
        None,
    )

    if not selected:
        raise HTTPException(
            status_code=400,
            detail=f"{exam} Result Checker is currently unavailable.",
        )

    try:
        unit_price = Decimal(str(selected["amount"])).quantize(Decimal("0.01"))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="BigiSub returned an invalid Result Checker price.",
        ) from exc

    if not unit_price.is_finite() or unit_price <= 0:
        raise HTTPException(
            status_code=502,
            detail="BigiSub returned an invalid Result Checker price.",
        )

    total_amount = (unit_price * payload.quantity).quantize(Decimal("0.01"))

    # Lock wallet and reserve funds before contacting the provider.
    wallet = _get_active_ngn_wallet(db, current_user.id)
    reference = f"ONTIME-RESULT-{uuid.uuid4().hex[:20].upper()}"

    transaction = WalletService.reserve_for_withdrawal(
        db,
        wallet_id=wallet.id,
        amount=total_amount,
        reference=reference,
        provider="bigisub",
        description=(
            f"{exam} Result Checker purchase, quantity {payload.quantity}"
        ),
    )
    transaction.transaction_type = "result_checker_purchase"
    db.commit()
    db.refresh(transaction)

    # Submit exactly one purchase request.
    try:
        provider_result = service.purchase_result_checker(
            exam=exam,
            quantity=payload.quantity,
        )
    except Exception:
        db.refresh(transaction)
        transaction.status = "pending"
        transaction.description = (
            (transaction.description or "")
            + " | Provider outcome uncertain; reconciliation required."
        )
        db.commit()

        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "exam": exam,
            "quantity": payload.quantity,
            "amount": str(total_amount),
            "message": (
                "Purchase status is being verified. "
                "Do not retry until the transaction is reconciled."
            ),
        }

    provider_result, provider_data, provider_status, provider_reference = (
        _provider_response(provider_result)
    )
    provider_success = provider_result.get("success") is True

    # Confirmed successful purchase.
    if provider_success and provider_status in {
        "successful", "success", "completed"
    }:
        transaction.status = "completed"
        transaction.provider_reference = provider_reference
        db.commit()

        return {
            "success": True,
            "status": "successful",
            "reference": reference,
            "exam": exam,
            "quantity": payload.quantity,
            "unit_price": str(unit_price),
            "total_amount": str(total_amount),
            "data": provider_data,
            "message": provider_result.get(
                "message",
                "Result Checker purchase successful.",
            ),
        }

    # Pending or ambiguous success: keep the funds reserved.
    if provider_status in {"pending", "processing"} or (
        provider_success and not provider_status
    ):
        transaction.status = "pending"
        transaction.provider_reference = provider_reference
        db.commit()

        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "exam": exam,
            "quantity": payload.quantity,
            "amount": str(total_amount),
            "message": (
                "BigiSub is processing this purchase. Do not retry yet."
            ),
        }

    # Refund only after an explicit, definitive rejection.
    explicitly_rejected = (
        provider_result.get("success") is False
        and provider_status in {
            "failed", "failure", "rejected", "declined"
        }
    )

    if not explicitly_rejected:
        transaction.status = "pending"
        transaction.provider_reference = provider_reference
        transaction.description = (
            (transaction.description or "")
            + " | Unrecognized provider response; reconciliation required."
        )
        db.commit()

        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "exam": exam,
            "quantity": payload.quantity,
            "message": (
                "Provider outcome could not be confirmed. "
                "Do not retry until reconciliation."
            ),
        }

    try:
        WalletService.credit(
            db,
            wallet_id=wallet.id,
            amount=total_amount,
            reference=f"{reference}-REFUND",
            transaction_type="result_checker_refund",
            provider="bigisub",
            provider_reference=provider_reference,
            description=f"Refund for rejected Result Checker purchase {reference}",
        )
        transaction.status = "failed"
        transaction.provider_reference = provider_reference
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=(
                "BigiSub rejected the purchase, but the refund could not "
                "be confirmed. Contact support before retrying."
            ),
        ) from exc

    raise HTTPException(
        status_code=400,
        detail=provider_result.get(
            "message",
            "BigiSub rejected the Result Checker purchase; refund recorded.",
        ),
    )


# ============================================================
# INTERNET / SMILE
# ============================================================

@router.get("/smile/plans")
def get_smile_plans(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_smile_plans()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# BETTING
# ============================================================

@router.get("/betting/billers")
def get_betting_billers(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_betting_billers()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ============================================================
# ELECTRICITY PROVIDERS
# ============================================================

@router.get("/electricity/providers")
def get_electricity_providers(
    current_user=Depends(get_current_user),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        result = service.get_electricity_providers()
        if not isinstance(result, dict):
            raise HTTPException(
                status_code=502,
                detail="BigiSub returned an invalid electricity providers response.",
            )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("BigiSub electricity providers request failed")
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve electricity providers from BigiSub.",
        ) from None


# ============================================================
# ELECTRICITY PURCHASE
# ============================================================

@router.post("/electricity/purchase")
def purchase_electricity(
    payload: ElectricityPurchaseRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    service: BigisubService = Depends(get_bigisub_service),
):
    _verify_transaction_pin(current_user, payload.transaction_pin)

    try:
        amount = Decimal(payload.amount).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid electricity amount.",
        ) from exc

    if not amount.is_finite() or amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Amount must be greater than zero.",
        )

    # Verify meter first.
    try:
        verification = service.verify_electricity_meter(
            company=payload.company,
            meter_no=payload.meter_no,
            meter_type=payload.meter_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Meter verification failed. No purchase was submitted.",
        ) from exc

    if not isinstance(verification, dict):
        raise HTTPException(
            status_code=502,
            detail="Invalid meter verification response.",
        )

    verified_data = verification.get("data")
    if not isinstance(verified_data, dict):
        verified_data = {}

    verified_status = str(
        verified_data.get("status", verification.get("status", ""))
    ).strip().lower()

    customer_name = str(verified_data.get("customer_name") or "").strip()
    verified_meter = str(
        verified_data.get("meter_number")
        or verified_data.get("meter_no")
        or ""
    ).strip()

    if verification.get("success") is not True or not customer_name:
        raise HTTPException(
            status_code=400,
            detail=verification.get(
                "message",
                "BigiSub could not verify the meter or customer name.",
            ),
        )

    if verified_status in {"failed", "failure", "rejected", "declined"}:
        raise HTTPException(
            status_code=400,
            detail="BigiSub rejected meter verification.",
        )

    if verified_meter and verified_meter != payload.meter_no:
        raise HTTPException(
            status_code=400,
            detail="Verified meter number does not match.",
        )

    # Retrieve provider fee and minimum amount.
    try:
        catalogue = service.get_electricity_providers()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to verify electricity provider pricing.",
        ) from exc

    if not isinstance(catalogue, dict):
        raise HTTPException(
            status_code=502,
            detail="Invalid electricity provider catalogue.",
        )

    provider_rows = catalogue.get("data")
    if isinstance(provider_rows, dict):
        provider_rows = provider_rows.get(
            "providers", provider_rows.get("results", [])
        )

    if not isinstance(provider_rows, list):
        raise HTTPException(
            status_code=502,
            detail="Electricity provider catalogue format is not recognized.",
        )

    selected = next(
        (
            row for row in provider_rows
            if isinstance(row, dict)
            and str(
                row.get("code")
                or row.get("id")
                or row.get("company")
                or row.get("slug")
                or ""
            ).strip().lower() == payload.company.strip().lower()
        ),
        None,
    )

    if selected is None:
        raise HTTPException(
            status_code=400,
            detail="Selected electricity provider is unavailable.",
        )

    try:
        fee = Decimal(str(selected.get("service_charge"))).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Invalid electricity service charge from BigiSub.",
        ) from exc

    if not fee.is_finite() or fee < 0:
        raise HTTPException(
            status_code=502,
            detail="Invalid electricity service charge.",
        )

    fee_type = str(
        selected.get("service_charge_type", "fixed")
    ).strip().lower()

    if fee_type in {"percentage", "percent", "%"}:
        fee = (amount * fee / Decimal("100")).quantize(Decimal("0.01"))
    elif fee_type not in {"fixed", "flat", "fixed_amount", ""}:
        raise HTTPException(
            status_code=502,
            detail="Unsupported electricity service charge type.",
        )

    minimum_key = (
        "min_amount_prepaid"
        if payload.meter_type == "prepaid"
        else "min_amount_postpaid"
    )
    minimum_raw = selected.get(minimum_key)
    if minimum_raw is None:
        minimum_raw = selected.get("min_amount")

    if minimum_raw is None:
        raise HTTPException(
            status_code=502,
            detail="BigiSub did not provide the minimum purchase amount.",
        )

    try:
        minimum_amount = Decimal(str(minimum_raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Invalid minimum electricity amount.",
        ) from exc

    if amount < minimum_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum electricity purchase is {minimum_amount}.",
        )

    total_amount = amount + fee
    wallet = _get_active_ngn_wallet(db, current_user.id)
    reference = f"ONTIME-ELECTRICITY-{uuid.uuid4().hex[:20].upper()}"

    transaction = WalletService.reserve_for_withdrawal(
        db,
        wallet_id=wallet.id,
        amount=total_amount,
        reference=reference,
        provider="bigisub",
        description=(
            f"Electricity purchase: {payload.company}, "
            f"meter ending {payload.meter_no[-4:]}, "
            f"{payload.meter_type}; amount {amount}, fee {fee}"
        ),
    )
    transaction.transaction_type = "electricity_purchase"
    db.commit()
    db.refresh(transaction)

    try:
        provider_result = service.purchase_electricity(
            company=payload.company,
            meter_no=payload.meter_no,
            meter_type=payload.meter_type,
            phone_number=payload.phone_number,
            amount=format(amount, ".2f"),
            customer_name=customer_name,
        )
    except Exception:
        db.refresh(transaction)
        transaction.status = "pending"
        transaction.description = (
            (transaction.description or "")
            + " | Provider outcome uncertain; reconciliation required."
        )
        db.commit()
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "amount": str(amount),
            "service_charge": str(fee),
            "total_reserved": str(total_amount),
            "message": "Provider outcome uncertain. Do not retry yet.",
        }

    provider_result, provider_data, provider_status, provider_reference = (
        _provider_response(provider_result)
    )
    provider_success = provider_result.get("success") is True

    if provider_success and provider_status in {
        "successful", "success", "completed"
    }:
        transaction.status = "completed"
        transaction.provider_reference = provider_reference
        db.commit()
        return {
            "success": True,
            "status": "successful",
            "reference": reference,
            "amount": str(amount),
            "service_charge": str(fee),
            "total_charged": str(total_amount),
            "data": provider_data,
            "message": provider_result.get(
                "message", "Electricity purchase successful."
            ),
        }

    if provider_status in {"pending", "processing"} or (
        provider_success and not provider_status
    ):
        transaction.status = "pending"
        transaction.provider_reference = provider_reference
        db.commit()
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "message": "BigiSub is processing the purchase. Do not retry yet.",
        }

    rejected = (
        provider_result.get("success") is False
        and provider_status in {"failed", "failure", "rejected", "declined"}
    )

    if not rejected:
        transaction.status = "pending"
        transaction.provider_reference = provider_reference
        transaction.description = (
            (transaction.description or "")
            + " | Unrecognized provider response; reconciliation required."
        )
        db.commit()
        return {
            "success": True,
            "status": "pending",
            "reference": reference,
            "message": "Provider outcome could not be confirmed. Do not retry.",
        }

    try:
        WalletService.credit(
            db,
            wallet_id=wallet.id,
            amount=total_amount,
            reference=f"{reference}-REFUND",
            transaction_type="electricity_purchase_refund",
            provider="bigisub",
            provider_reference=provider_reference,
            description=f"Refund for rejected electricity purchase {reference}",
        )
        transaction.status = "failed"
        transaction.provider_reference = provider_reference
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Purchase rejected but refund could not be confirmed. Contact support.",
        ) from exc

    raise HTTPException(
        status_code=400,
        detail=provider_result.get(
            "message",
            "BigiSub rejected the purchase; refund recorded.",
        ),
    )