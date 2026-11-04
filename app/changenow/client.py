import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from app.core.config import settings


class ChangeNOWClient:
    """ChangeNOW API client using Python's standard HTTPS transport."""

    def __init__(self) -> None:
        self.base_url = (settings.CHANGENOW_BASE_URL or "").rstrip("/")
        self.api_key = settings.CHANGENOW_API_KEY

        if not self.base_url:
            raise RuntimeError("CHANGENOW_BASE_URL is not configured.")

        if not self.api_key:
            raise RuntimeError("CHANGENOW_API_KEY is not configured.")

        self.timeout = 30

    def _headers(self, method: str) -> dict[str, str]:
        headers = {
            "x-changenow-api-key": self.api_key,
            "Accept": "application/json",
        }

        if method.upper() != "GET":
            headers["Content-Type"] = "application/json"

        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
    ) -> dict | list:
        method = method.upper()
        url = self._url(path)

        if params:
            url = f"{url}?{urlencode(params)}"

        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        attempts = 3 if method == "GET" else 1
        last_error = None

        for attempt in range(attempts):
            # Create a fresh Request for every attempt.
            request = Request(
                url=url,
                data=body,
                headers=self._headers(method),
                method=method,
            )

            try:
                with urlopen(request, timeout=self.timeout) as response:
                    response_body = response.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                    status_code = response.status

                if not 200 <= status_code < 300:
                    raise RuntimeError(
                        f"ChangeNOW returned HTTP {status_code}."
                    )

                try:
                    return json.loads(response_body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "ChangeNOW returned an invalid JSON response."
                    ) from exc

            except HTTPError as exc:
                error_body = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )
                raise RuntimeError(
                    f"ChangeNOW HTTP {exc.code}: {error_body[:1000]}"
                ) from exc

            except (URLError, OSError, TimeoutError) as exc:
                last_error = exc

                if attempt + 1 < attempts:
                    time.sleep(1 * (2 ** attempt))

        raise RuntimeError(
            f"Could not connect to ChangeNOW after {attempts} "
            f"attempts: {last_error}"
        ) from last_error

    def get_available_currencies(self) -> list:
        result = self._request(
            "GET",
            "/v2/exchange/currencies",
            params={"active": "true", "flow": "standard"},
        )

        if not isinstance(result, list):
            raise RuntimeError(
                "Unexpected ChangeNOW currencies response format."
            )

        return result

    def create_exchange(
        self,
        *,
        from_currency: str,
        to_currency: str,
        from_amount: str,
        address: str,
        from_network: str | None = None,
        to_network: str | None = None,
        extra_id: str | None = None,
        refund_address: str | None = None,
        refund_extra_id: str | None = None,
        user_id: str | None = None,
        contact_email: str | None = None,
        source: str | None = None,
        flow: str = "standard",
        exchange_type: str = "direct",
        rate_id: str | None = None,
    ) -> dict:
        payload = {
            "fromCurrency": from_currency.strip().lower(),
            "toCurrency": to_currency.strip().lower(),
            "fromAmount": from_amount,
            "address": address.strip(),
            "flow": flow,
            "type": exchange_type,
        }

        optional_fields = {
            "fromNetwork": from_network,
            "toNetwork": to_network,
            "extraId": extra_id,
            "refundAddress": refund_address,
            "refundExtraId": refund_extra_id,
            "userId": user_id,
            "contactEmail": contact_email,
            "source": source,
            "rateId": rate_id,
        }

        payload.update({
            key: value
            for key, value in optional_fields.items()
            if value is not None and value != ""
        })

        result = self._request(
            "POST",
            "/v2/exchange",
            payload=payload,
        )

        if not isinstance(result, dict):
            raise RuntimeError(
                "Unexpected ChangeNOW exchange response format."
            )

        return result

    def get_exchange_status(self, transaction_id: str) -> dict:
        if not transaction_id or not transaction_id.strip():
            raise ValueError("Transaction ID is required.")

        safe_id = quote(transaction_id.strip(), safe="")

        result = self._request(
            "GET",
            f"/v2/exchange/by-id/{safe_id}",
        )

        if not isinstance(result, dict):
            raise RuntimeError(
                "Unexpected ChangeNOW exchange-status response format." 
            )

        return result
