
from typing import Any
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings


class BigisubClient:
    """HTTP client for BigiSub provider APIs."""

    def __init__(self) -> None:
        self.base_url = settings.BIGISUB_BASE_URL.rstrip("/")
        self.api_key = settings.BIGISUB_API_KEY

        if not self.base_url:
            raise RuntimeError("BigiSub base URL is not configured.")

    # ============================================================
    # HEADERS AND URL
    # ============================================================

    def _headers(self) -> dict[str, str]:
        if not self.api_key or not self.api_key.strip():
            raise RuntimeError(
                "BigiSub API credentials are not configured."
            )

        return {
            "Authorization": f"Token {self.api_key.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    # ============================================================
    # HTTP HELPERS
    # ============================================================

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float = 30.0,
        preserve_error_body: bool = False,
    ) -> dict[str, Any]:
        """
        Send exactly one provider request.

        Purchase requests must not be automatically retried because
        the provider may process a payment before a timeout occurs.
        """

        try:
            with httpx.Client(
                http2=False,
                follow_redirects=True,
                timeout=timeout,
            ) as client:
                response = client.request(
                    method=method,
                    url=self._url(path),
                    headers=self._headers(),
                    json=json,
                )

        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "BigiSub request timed out. For a purchase, "
                "reconcile its status before attempting another transaction."
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Could not connect to BigiSub "
                f"({type(exc).__name__})."
            ) from exc

        try:
            body = response.json()

        except ValueError as exc:
            if response.is_error:
                raise RuntimeError(
                    f"BigiSub returned HTTP {response.status_code} "
                    "with a non-JSON response."
                ) from exc

            raise RuntimeError(
                "BigiSub returned an invalid JSON response."
            ) from exc

        if not isinstance(body, dict):
            raise RuntimeError(
                "BigiSub returned an unexpected response format."
            )

        if response.is_error and not (
            preserve_error_body and "success" in body
        ):
            raise RuntimeError(
                f"BigiSub returned HTTP {response.status_code}. "
                "Inspect the provider response securely."
            )

        return body

    def _get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        timeout: float = 30.0,
        preserve_error_body: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            path,
            json=payload,
            timeout=timeout,
            preserve_error_body=preserve_error_body,
        )

    # ============================================================
    # LOGIN
    # ============================================================

    def login(
        self,
        email_or_username: str,
        password: str,
    ) -> dict[str, Any]:
        return self._post(
            "/api/v2/auth/login/",
            {
                "email_or_username": email_or_username,
                "password": password,
            },
        )

    # ============================================================
    # BIGISUB WALLET BALANCE
    # ============================================================

    def get_wallet_balance(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/financial/wallet/balance/"
        )

    # ============================================================
    # AIRTIME PURCHASE - ORIGINAL BIGISUB API
    # ============================================================

    def purchase_airtime(
        self,
        network: int,
        phone_number: str,
        amount: str,
        airtime_type: str = "vtu",
    ) -> dict[str, Any]:
        """
        Original BigiSub airtime endpoint.

        POST /api/v2/vtu/airtime/purchase/

        Provider payload:
        {
            "network": 1,
            "phone_number": "08012345678",
            "amount": "100",
            "airtime_type": "vtu",
            "pin": "<provider PIN>"
        }

        The provider PIN is never accepted from Flutter.
        The caller must separately verify the customer's PIN,
        reserve wallet funds and record the transaction.
        """

        provider_pin = (
            settings.BIGISUB_PROVIDER_PIN or ""
        ).strip()

        if not provider_pin:
            raise RuntimeError(
                "BigiSub provider PIN is not configured."
            )

        if (
            isinstance(network, bool)
            or not isinstance(network, int)
            or network <= 0
        ):
            raise ValueError(
                "A valid BigiSub network ID is required."
            )

        phone_number = phone_number.strip()

        if not phone_number:
            raise ValueError(
                "Customer phone number is required."
            )

        airtime_type = airtime_type.strip().lower()

        if airtime_type != "vtu":
            raise ValueError(
                "Only VTU airtime purchases are supported."
            )

        try:
            numeric_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(
                "Airtime amount must be numeric."
            ) from exc

        if not numeric_amount.is_finite() or numeric_amount <= 0:
            raise ValueError(
                "Airtime amount must be a positive finite number."
            )

        payload = {
            "network": network,
            "phone_number": phone_number,
            "amount": str(numeric_amount),
            "airtime_type": "vtu",
            "pin": provider_pin,
        }

        return self._post(
            "/api/v2/vtu/airtime/purchase/",
            payload,
            timeout=60.0,
            preserve_error_body=True,
        )

    # ============================================================
    # DATA PLANS
    # ============================================================

    def get_data_plans(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/vtu/data/plans/"
        )

    # ============================================================
    # DATA PURCHASE
    # ============================================================

    def purchase_data(
        self,
        network: int,
        plan: int,
        phone_number: str,
        ported_number: bool = False,
    ) -> dict[str, Any]:

        provider_pin = (
            settings.BIGISUB_PROVIDER_PIN or ""
        ).strip()

        if not provider_pin:
            raise RuntimeError(
                "BigiSub provider PIN is not configured."
            )

        payload = {
            "network": network,
            "plan": plan,
            "phone_number": phone_number,
            "pin": provider_pin,
            "ported_number": ported_number,
        }

        return self._post(
            settings.BIGISUB_DATA_PURCHASE_PATH,
            payload,
            timeout=60.0,
            preserve_error_body=True,
        )

    # ============================================================
    # CABLE TV
    # ============================================================

    def get_cable_plans(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/vtu/cable/plans/"
        )

    # ============================================================
    # RECHARGE PIN
    # ============================================================

    def get_recharge_pin_plans(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/vtu/recharge-pin/plans/"
        )

    # ============================================================
    # RESULT CHECKER PRICES
    # ============================================================

    def get_result_checker_prices(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/bills/result-checker/prices/"
        )

    # ============================================================
    # RESULT CHECKER PURCHASE
    # ============================================================

    def purchase_result_checker(
        self,
        exam: str,
        quantity: int,
    ) -> dict[str, Any]:

        provider_pin = (
            settings.BIGISUB_PROVIDER_PIN or ""
        ).strip()

        if not provider_pin:
            raise RuntimeError(
                "BigiSub provider PIN is not configured."
            )

        exam = exam.strip().upper()

        if exam not in {"WAEC", "NECO", "NABTEB"}:
            raise ValueError(
                "Unsupported examination type."
            )

        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError(
                "Quantity must be a valid integer."
            )

        if quantity < 1 or quantity > 20:
            raise ValueError(
                "Quantity must be between 1 and 20."
            )

        payload = {
            "exam": exam,
            "quantity": quantity,
            "pin_code": provider_pin,
        }

        return self._post(
            "/api/v2/bills/result-checker/purchase/",
            payload,
            timeout=60.0,
            preserve_error_body=True,
        )

    # ============================================================
    # SMILE INTERNET
    # ============================================================

    def get_smile_plans(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/isp/smile/plans/"
        )

    # ============================================================
    # BETTING
    # ============================================================

    def get_betting_billers(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/betting/billers/"
        )

    # ============================================================
    # ELECTRICITY PROVIDERS
    # ============================================================

    def get_electricity_providers(self) -> dict[str, Any]:
        return self._get(
            "/api/v2/bills/electricity/providers/"
        )

    # ============================================================
    # ELECTRICITY METER VERIFICATION
    # ============================================================

    def verify_electricity_meter(
        self,
        company: str,
        meter_no: str,
        meter_type: str,
    ) -> dict[str, Any]:

        if not company.strip():
            raise ValueError(
                "Electricity company is required."
            )

        if not meter_no.strip():
            raise ValueError(
                "Electricity meter number is required."
            )

        if meter_type not in {"prepaid", "postpaid"}:
            raise ValueError(
                "Meter type must be prepaid or postpaid."
            )

        payload = {
            "company": company.strip(),
            "meter_no": meter_no.strip(),
            "meter_type": meter_type,
        }

        return self._post(
            "/api/v2/bills/electricity/verify/",
            payload,
        )

    # ============================================================
    # ELECTRICITY PURCHASE
    # ============================================================

    def purchase_electricity(
        self,
        company: str,
        meter_no: str,
        meter_type: str,
        phone_number: str,
        amount: str,
        customer_name: str,
    ) -> dict[str, Any]:

        provider_pin = (
            settings.BIGISUB_PROVIDER_PIN or ""
        ).strip()

        if not provider_pin:
            raise RuntimeError(
                "BigiSub provider PIN is not configured."
            )

        if not company.strip():
            raise ValueError(
                "Electricity company is required."
            )

        if not meter_no.strip():
            raise ValueError(
                "Electricity meter number is required."
            )

        if meter_type not in {"prepaid", "postpaid"}:
            raise ValueError(
                "Meter type must be prepaid or postpaid."
            )

        if not phone_number.strip():
            raise ValueError(
                "Customer phone number is required."
            )

        if not customer_name.strip():
            raise ValueError(
                "Verified electricity customer name is required."
            )

        try:
            numeric_amount = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Electricity amount must be numeric."
            ) from exc

        if (
            not numeric_amount > 0
            or numeric_amount == float("inf")
            or numeric_amount != numeric_amount
        ):
            raise ValueError(
                "Electricity amount must be a positive finite number."
            )

        payload = {
            "company": company.strip(),
            "meter_no": meter_no.strip(),
            "meter_type": meter_type,
            "phone_number": phone_number.strip(),
            "amount": numeric_amount,
            "Customer_name": customer_name.strip(),
            "pin": provider_pin,
        }

        return self._post(
            "/api/v2/bills/electricity/pay/",
            payload,
            timeout=60.0,
            preserve_error_body=True,
        )
