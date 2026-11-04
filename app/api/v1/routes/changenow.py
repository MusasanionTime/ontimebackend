import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.changenow.service import ChangeNOWService
from app.database.database import get_db
from app.models.crypto_exchange import CryptoExchange
from app.models.user import User
from app.schemas.changenow import (
    ChangeNOWExchangeCreate,
    ChangeNOWExchangeResponse,
    ChangeNOWPairValidationResponse,
)


router = APIRouter(
    prefix="/changenow",
    tags=["ChangeNOW"],
)


# ============================================================
# HELPERS
# ============================================================


def _exchange_response(
    exchange: CryptoExchange,
) -> ChangeNOWExchangeResponse:
    return ChangeNOWExchangeResponse(
        id=str(exchange.id),
        provider=exchange.provider,
        provider_transaction_id=exchange.provider_transaction_id,
        from_currency=exchange.from_currency,
        to_currency=exchange.to_currency,
        from_network=exchange.from_network,
        to_network=exchange.to_network,
        from_amount=exchange.from_amount,
        to_amount=exchange.to_amount,
        destination_address=exchange.destination_address,
        refund_address=exchange.refund_address,
        deposit_address=exchange.deposit_address,
        deposit_extra_id=exchange.deposit_extra_id,
        status=exchange.status,
        rate_id=exchange.rate_id,
        created_at=exchange.created_at.isoformat(),
        updated_at=exchange.updated_at.isoformat(),
    )


def _first_value(
    data: dict,
    *keys: str,
):
    for key in keys:
        value = data.get(key)

        if value is not None:
            return value

    return None


def _decimal_or_none(value):
    if value is None:
        return None

    try:
        return Decimal(str(value))

    except (ValueError, TypeError):
        return None


def _normalize_webhook_status(
    service: ChangeNOWService,
    payload: dict,
) -> str | None:
    raw_status = _first_value(
        payload,
        "status",
        "state",
    )

    if not raw_status:
        return None

    return service.normalize_status(
        str(raw_status)
    )


# ============================================================
# GET CURRENCIES
# ============================================================


@router.get("/currencies")
def get_currencies(
    current_user: User = Depends(get_current_user),
):
    service = ChangeNOWService()

    try:
        return service.get_currencies()

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Unable to retrieve ChangeNOW currencies: "
                f"{str(exc)}"
            ),
        ) from exc


# ============================================================
# VALIDATE CURRENCY PAIR
# ============================================================


@router.get(
    "/validate",
    response_model=ChangeNOWPairValidationResponse,
)
def validate_currency_pair(
    from_currency: str,
    to_currency: str,
    from_network: str | None = None,
    to_network: str | None = None,
    current_user: User = Depends(get_current_user),
):
    service = ChangeNOWService()

    try:
        result = service.validate_currency_pair(
            from_currency=from_currency,
            to_currency=to_currency,
            from_network=from_network,
            to_network=to_network,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Unable to validate ChangeNOW pair: "
                f"{str(exc)}"
            ),
        ) from exc

    return ChangeNOWPairValidationResponse(
        valid=result["valid"],
        from_currency=result["from"]["ticker"],
        to_currency=result["to"]["ticker"],
        from_network=result["from"].get("network"),
        to_network=result["to"].get("network"),
    )


# ============================================================
# CREATE EXCHANGE
# ============================================================


@router.post(
    "/exchanges",
    response_model=ChangeNOWExchangeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_exchange(
    payload: ChangeNOWExchangeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = ChangeNOWService()

    try:
        response = service.create_exchange(
            from_currency=payload.from_currency,
            to_currency=payload.to_currency,
            from_amount=str(payload.from_amount),
            address=payload.address,
            from_network=payload.from_network,
            to_network=payload.to_network,
            extra_id=payload.extra_id,
            refund_address=payload.refund_address,
            refund_extra_id=payload.refund_extra_id,
            user_id=str(current_user.id),
            contact_email=str(current_user.email),
            flow=payload.flow,
            exchange_type=payload.exchange_type,
            rate_id=payload.rate_id,
        )

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ChangeNOW error: {str(exc)}",
        ) from exc

    provider_transaction_id = _first_value(
        response,
        "id",
        "transactionId",
        "transaction_id",
    )

    if not provider_transaction_id:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ChangeNOW returned no transaction ID.",
        )

    to_amount = _decimal_or_none(
        _first_value(
            response,
            "toAmount",
            "amountReceive",
            "expectedReceiveAmount",
        )
    )

    exchange = CryptoExchange(
        id=uuid.uuid4(),
        user_id=current_user.id,
        provider="changenow",
        provider_transaction_id=str(
            provider_transaction_id
        ),
        from_currency=payload.from_currency.lower(),
        to_currency=payload.to_currency.lower(),
        from_network=payload.from_network,
        to_network=payload.to_network,
        from_amount=payload.from_amount,
        to_amount=to_amount,
        destination_address=payload.address,
        refund_address=payload.refund_address,
        deposit_address=_first_value(
            response,
            "payinAddress",
            "depositAddress",
        ),
        deposit_extra_id=_first_value(
            response,
            "payinExtraId",
            "depositExtraId",
        ),
        status=service.normalize_status(
            response.get(
                "status",
                "waiting",
            )
        ),
        rate_id=(
            _first_value(
                response,
                "rateId",
                "rate_id",
            )
            or payload.rate_id
        ),
        provider_response=json.dumps(
            response,
            default=str,
        ),
    )

    db.add(exchange)

    try:
        db.commit()
        db.refresh(exchange)

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Unable to save ChangeNOW exchange: "
                f"{str(exc)}"
            ),
        ) from exc

    return _exchange_response(exchange)


# ============================================================
# GET EXCHANGE HISTORY
# ============================================================


@router.get(
    "/exchanges",
    response_model=list[ChangeNOWExchangeResponse],
)
def get_exchange_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exchanges = db.scalars(
        select(CryptoExchange)
        .where(
            CryptoExchange.user_id == current_user.id
        )
        .order_by(
            CryptoExchange.created_at.desc()
        )
    ).all()

    return [
        _exchange_response(exchange)
        for exchange in exchanges
    ]


# ============================================================
# GET SINGLE EXCHANGE
# ============================================================


@router.get(
    "/exchanges/{exchange_id}",
    response_model=ChangeNOWExchangeResponse,
)
def get_exchange(
    exchange_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exchange = db.scalar(
        select(CryptoExchange).where(
            CryptoExchange.id == exchange_id,
            CryptoExchange.user_id == current_user.id,
        )
    )

    if not exchange:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exchange not found.",
        )

    # ========================================================
    # REFRESH STATUS FROM CHANGENOW
    # ========================================================

    if exchange.provider_transaction_id:
        service = ChangeNOWService()

        try:
            provider_status = (
                service.get_exchange_status(
                    exchange.provider_transaction_id
                )
            )

            latest_status = provider_status.get(
                "status"
            )

            if latest_status:
                current_status = exchange.status

                if service.is_valid_status_transition(
                    current_status,
                    latest_status,
                ):
                    exchange.status = (
                        service.normalize_status(
                            latest_status
                        )
                    )

            latest_to_amount = _first_value(
                provider_status,
                "toAmount",
                "amountTo",
                "expectedAmountTo",
                "amountReceive",
            )

            if latest_to_amount is not None:
                parsed_to_amount = _decimal_or_none(
                    latest_to_amount
                )

                if parsed_to_amount is not None:
                    exchange.to_amount = (
                        parsed_to_amount
                    )

            exchange.provider_response = json.dumps(
                provider_status,
                default=str,
            )

            db.commit()
            db.refresh(exchange)

        except Exception:
            # Keep the last known database state if
            # ChangeNOW is temporarily unavailable.
            db.rollback()

    return _exchange_response(exchange)


# ============================================================
# CHANGENOW WEBHOOK / CALLBACK
# ============================================================


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
)
async def changenow_webhook(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """
    Receive ChangeNOW exchange status callbacks.

    This endpoint does not use ONTIME SUBDATA LTD user
    authentication because it is intended for provider
    callbacks.
    """

    # ========================================================
    # VALIDATE PAYLOAD
    # ========================================================

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Webhook payload must be a JSON object."
            ),
        )

    # ========================================================
    # FIND PROVIDER TRANSACTION ID
    # ========================================================

    provider_transaction_id = _first_value(
        payload,
        "id",
        "transactionId",
        "transaction_id",
    )

    if not provider_transaction_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Webhook payload contains no "
                "transaction ID."
            ),
        )

    provider_transaction_id = str(
        provider_transaction_id
    )

    # ========================================================
    # FIND EXISTING EXCHANGE
    # ========================================================

    exchange = db.scalar(
        select(CryptoExchange).where(
            CryptoExchange.provider == "changenow",
            CryptoExchange.provider_transaction_id
            == provider_transaction_id,
        )
    )

    # ========================================================
    # UNKNOWN TRANSACTION
    # ========================================================

    if not exchange:
        return {
            "success": True,
            "processed": False,
            "message": "Exchange not found.",
        }

    service = ChangeNOWService()

    # ========================================================
    # UPDATE STATUS
    # ========================================================

    latest_status = _normalize_webhook_status(
        service,
        payload,
    )

    status_changed = False

    if latest_status:
        current_status = exchange.status

        if service.is_valid_status_transition(
            current_status,
            latest_status,
        ):
            if current_status != latest_status:
                exchange.status = latest_status
                status_changed = True

    # ========================================================
    # UPDATE TO AMOUNT
    # ========================================================

    latest_to_amount = _first_value(
        payload,
        "toAmount",
        "amountReceive",
        "expectedReceiveAmount",
        "amountTo",
    )

    if latest_to_amount is not None:
        parsed_to_amount = _decimal_or_none(
            latest_to_amount
        )

        if parsed_to_amount is not None:
            exchange.to_amount = (
                parsed_to_amount
            )

    # ========================================================
    # UPDATE DEPOSIT ADDRESS
    # ========================================================

    deposit_address = _first_value(
        payload,
        "payinAddress",
        "depositAddress",
    )

    if deposit_address:
        exchange.deposit_address = str(
            deposit_address
        )

    # ========================================================
    # UPDATE DEPOSIT EXTRA ID
    # ========================================================

    deposit_extra_id = _first_value(
        payload,
        "payinExtraId",
        "depositExtraId",
    )

    if deposit_extra_id is not None:
        exchange.deposit_extra_id = str(
            deposit_extra_id
        )

    # ========================================================
    # UPDATE REFUND ADDRESS
    # ========================================================

    refund_address = payload.get(
        "refundAddress"
    )

    if refund_address:
        exchange.refund_address = str(
            refund_address
        )

    # ========================================================
    # STORE PROVIDER PAYLOAD
    # ========================================================

    incoming_provider_response = json.dumps(
        payload,
        sort_keys=True,
        default=str,
    )

    if exchange.provider_response != (
        incoming_provider_response
    ):
        exchange.provider_response = (
            incoming_provider_response
        )

    # ========================================================
    # SAVE CHANGES
    # ========================================================

    try:
        db.commit()
        db.refresh(exchange)

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Unable to persist "
                "ChangeNOW webhook."
            ),
        ) from exc

    # ========================================================
    # RESPONSE
    # ========================================================

    return {
        "success": True,
        "processed": True,
        "status_changed": status_changed,
        "exchange_id": str(exchange.id),
        "provider_transaction_id": (
            exchange.provider_transaction_id
        ),
        "status": exchange.status,
    }