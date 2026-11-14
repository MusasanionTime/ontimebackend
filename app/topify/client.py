from urllib.parse import quote

import httpx

from app.core.config import settings


class TopifyClient:
    """Small authenticated client for documented Topify Gateway endpoints."""

    def __init__(self, *, timeout: float = 20.0):
        self.base_url = (settings.TOPIFY_BASE_URL or "").rstrip("/")
        self.api_key = settings.TOPIFY_API_KEY or ""
        self.timeout = timeout
        if not self.base_url or not self.api_key:
            raise RuntimeError("Topify API configuration is incomplete.")

    def _request(
        self, method: str, path: str, *, json_body: dict | None = None
    ) -> dict:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout), follow_redirects=False
            ) as client:
                response = client.request(
                    method,
                    f"{self.base_url}{path}",
                    json=json_body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "Topify request timed out; retry using the same customer details."
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError("Unable to connect to Topify.") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Topify returned invalid JSON (HTTP {response.status_code})."
            ) from exc

        if (
            response.is_error
            or not isinstance(payload, dict)
            or payload.get("status") is not True
        ):
            raise RuntimeError(f"Topify request failed (HTTP {response.status_code}).")
        return payload

    def reserve_virtual_account(
        self, *, email: str, name: str, phone_number: str, business_id: str
    ) -> dict:
        # Deliberately allowlist fields. Do not send BVN, NIN or PalmPay identity fields.
        payload = self._request(
            "POST",
            "/api/v1/virtual-accounts/reserve",
            json_body={
                "email": email,
                "name": name,
                "phoneNumber": phone_number,
                "bankCode": ["30901"],
                "businessId": business_id,
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Topify reservation response is incomplete.")  # noqa: TRY004
        return data

    def get_customer_accounts(self, customer_code: str) -> list[dict]:
        payload = self._request(
            "GET",
            f"/api/v1/virtual-accounts/customer/{quote(customer_code, safe='')}",
        )
        data = payload.get("data")
        if not isinstance(data, list) or any(
            not isinstance(item, dict) for item in data
        ):
            raise RuntimeError("Topify account response is incomplete.")
        return data

    def verify_transaction(self, reference: str) -> dict:
        payload = self._request(
            "GET",
            f"/api/v1/transactions/verify/{quote(reference, safe='')}",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError(  # noqa: TRY004
                "Topify transaction verification response is incomplete."
            )
        return data
