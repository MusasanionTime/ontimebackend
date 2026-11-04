from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.admin import get_current_admin
from app.bigisub.service import BigisubService
from app.models.admin import Admin
from app.schemas.admin_bigisub import (
    AdminBigisubStatusResponse,
    AdminBigisubWalletResponse,
)


router = APIRouter(
    prefix="/admin/bigisub",
    tags=["Admin Bigisub"],
)


def get_bigisub_service() -> BigisubService:
    return BigisubService()


def _build_wallet_response(data: dict) -> AdminBigisubWalletResponse:
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Bigisub wallet response does not contain valid data",
        )

    return AdminBigisubWalletResponse(
        id=data.get("id"),
        username=data.get("username"),
        email=data.get("email"),
        full_name=data.get("full_name"),
        balance=Decimal(str(data.get("balance", "0"))),
        pending_amount=Decimal(
            str(data.get("pending_amount", "0"))
        ),
        referal_balance=Decimal(
            str(data.get("referal_balance", "0"))
        ),
        user_type=data.get("user_type"),
        reserved_account_number=data.get(
            "reserved_account_number"
        ),
        bank_name=data.get("bank_name"),
        account_name=data.get("account_name"),
    )


def _provider_data_response(
    response: dict,
    default_message: str,
) -> dict:
    if not isinstance(response, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response received from Bigisub",
        )

    if response.get("success") is False:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=response.get(
                "message",
                default_message,
            ),
        )

    return response


@router.get(
    "/wallet",
    response_model=AdminBigisubWalletResponse,
)
def admin_get_bigisub_wallet(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        response = service.get_wallet_balance()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    response = _provider_data_response(
        response,
        "Bigisub wallet request failed",
    )

    return _build_wallet_response(response.get("data"))


@router.get(
    "/status",
    response_model=AdminBigisubStatusResponse,
)
def admin_get_bigisub_status(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        response = service.get_wallet_balance()
    except RuntimeError as exc:
        return AdminBigisubStatusResponse(
            provider="bigisub",
            status="unavailable",
            message=str(exc),
            wallet=AdminBigisubWalletResponse(
                id=0,
                username="",
                email="",
                full_name="",
                balance=Decimal("0"),
                pending_amount=Decimal("0"),
                referal_balance=Decimal("0"),
                user_type="",
            ),
        )

    if not isinstance(response, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response received from Bigisub",
        )

    if response.get("success") is False:
        return AdminBigisubStatusResponse(
            provider="bigisub",
            status="unavailable",
            message=response.get(
                "message",
                "Bigisub provider request failed",
            ),
            wallet=AdminBigisubWalletResponse(
                id=0,
                username="",
                email="",
                full_name="",
                balance=Decimal("0"),
                pending_amount=Decimal("0"),
                referal_balance=Decimal("0"),
                user_type="",
            ),
        )

    wallet = _build_wallet_response(response.get("data"))

    return AdminBigisubStatusResponse(
        provider="bigisub",
        status="connected",
        message=response.get(
            "message",
            "Bigisub provider is connected",
        ),
        wallet=wallet,
    )


@router.get("/data/plans")
def admin_get_data_plans(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_data_plans()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/cable/plans")
def admin_get_cable_plans(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_cable_plans()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/recharge-pin/plans")
def admin_get_recharge_pin_plans(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_recharge_pin_plans()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/result-checker/prices")
def admin_get_result_checker_prices(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_result_checker_prices()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/smile/plans")
def admin_get_smile_plans(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_smile_plans()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/betting/billers")
def admin_get_betting_billers(
    admin: Admin = Depends(get_current_admin),
    service: BigisubService = Depends(get_bigisub_service),
):
    try:
        return service.get_betting_billers()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc