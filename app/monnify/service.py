import uuid

import httpx

from app.core.config import settings
from app.monnify.client import MonnifyClient


class MonnifyService:

    def __init__(self):
        self.client = MonnifyClient()

    def get_access_token(self) -> str:
        return self.client.authenticate()

    def create_reserved_account(
        self,
        *,
        account_name: str,
        customer_email: str,
        customer_name: str,
        bvn: str | None = None,
        nin: str | None = None,
        get_all_available_banks: bool = True,
    ) -> dict:

        if not bvn and not nin:
            raise ValueError(
                "BVN or NIN is required to create a Monnify reserved account."
            )

        account_reference = (
            f"GALAXY-{uuid.uuid4().hex[:20].upper()}"
        )

        payload = {
            "accountReference": account_reference,
            "accountName": account_name,
            "currencyCode": "NGN",
            "contractCode": settings.MONNIFY_CONTRACT_CODE,
            "customerEmail": customer_email,
            "customerName": customer_name,
            "getAllAvailableBanks": get_all_available_banks,
        }

        if bvn:
            payload["bvn"] = bvn

        if nin:
            payload["nin"] = nin

        token = self.client.authenticate()

        url = (
            f"{settings.MONNIFY_BASE_URL.rstrip('/')}"
            "/api/v2/bank-transfer/reserved-accounts"
        )

        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Unable to connect to Monnify."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Monnify returned an invalid response."
            ) from exc

        if response.is_error:
            message = data.get(
                "responseMessage",
                "Monnify request failed.",
            )

            raise RuntimeError(
                f"Monnify HTTP {response.status_code}: {message}"
            )

        if not data.get("requestSuccessful"):
            raise RuntimeError(
                data.get(
                    "responseMessage",
                    "Monnify reserved-account creation failed.",
                )
            )

        response_body = data.get(
            "responseBody"
        )

        if not response_body:
            raise RuntimeError(
                "Monnify returned an empty account response."
            )

        return response_body

    def validate_bank_account(
        self,
        *,
        account_number: str,
        bank_code: str,
    ) -> dict:
        """
        Verify a Nigerian bank account using
        Monnify Name Enquiry.
        """

        token = self.client.authenticate()

        url = (
            f"{settings.MONNIFY_BASE_URL.rstrip('/')}"
            "/api/v2/disbursements/account/validate"
        )

        try:
            response = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params={
                    "accountNumber": account_number,
                    "bankCode": bank_code,
                },
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Unable to connect to Monnify."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Monnify returned an invalid response."
            ) from exc

        if response.is_error:
            message = data.get(
                "responseMessage",
                "Bank account validation failed.",
            )

            raise RuntimeError(
                f"Monnify HTTP {response.status_code}: {message}"
            )

        if not data.get("requestSuccessful"):
            raise RuntimeError(
                data.get(
                    "responseMessage",
                    "Unable to validate bank account.",
                )
            )

        response_body = data.get(
            "responseBody"
        )

        if not response_body:
            raise RuntimeError(
                "Monnify returned an empty bank account response."
            )

        return response_body

    def initiate_single_transfer(
        self,
        *,
        amount: float,
        reference: str,
        narration: str,
        destination_bank_code: str,
        destination_account_number: str,
        destination_account_name: str,
        currency: str = "NGN",
        async_transfer: bool = True,
    ) -> dict:
        """
        Initiate a Monnify single disbursement transfer.

        The destination account name must come from a
        successful Monnify Name Enquiry response.
        """

        if amount <= 0:
            raise ValueError(
                "Transfer amount must be greater than zero."
            )

        if not reference.strip():
            raise ValueError(
                "Transfer reference is required."
            )

        if not narration.strip():
            raise ValueError(
                "Transfer narration is required."
            )

        if not destination_bank_code.strip():
            raise ValueError(
                "Destination bank code is required."
            )

        if not destination_account_number.strip():
            raise ValueError(
                "Destination account number is required."
            )

        if not destination_account_name.strip():
            raise ValueError(
                "Destination account name is required."
            )

        token = self.client.authenticate()

        url = (
            f"{settings.MONNIFY_BASE_URL.rstrip('/')}"
            "/api/v2/disbursements/single"
        )

        payload = {
            "amount": amount,
            "reference": reference,
            "narration": narration,
            "destinationBankCode": (
                destination_bank_code
            ),
            "destinationAccountNumber": (
                destination_account_number
            ),
            "destinationAccountName": (
                destination_account_name
            ),
            "currency": currency,
            "async": async_transfer,
        }

        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Unable to connect to Monnify disbursement service."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Monnify returned an invalid disbursement response."
            ) from exc

        if response.is_error:
            message = data.get(
                "responseMessage",
                "Monnify disbursement request failed.",
            )

            raise RuntimeError(
                f"Monnify HTTP {response.status_code}: {message}"
            )

        if not data.get("requestSuccessful"):
            raise RuntimeError(
                data.get(
                    "responseMessage",
                    "Monnify disbursement request failed.",
                )
            )

        response_body = data.get(
            "responseBody"
        )

        if not response_body:
            raise RuntimeError(
                "Monnify returned an empty disbursement response."
            )

        return response_body

    def get_single_transfer_status(
        self,
        *,
        reference: str,
    ) -> dict:
        """
        Get the current status of a Monnify single transfer.
        """

        if not reference.strip():
            raise ValueError(
                "Transfer reference is required."
            )

        token = self.client.authenticate()

        url = (
            f"{settings.MONNIFY_BASE_URL.rstrip('/')}"
            "/api/v2/disbursements/single/summary"
        )

        try:
            response = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                params={
                    "reference": reference,
                },
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Unable to connect to Monnify transfer status service."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Monnify returned an invalid transfer status response."
            ) from exc

        if response.is_error:
            message = data.get(
                "responseMessage",
                "Monnify transfer status request failed.",
            )

            raise RuntimeError(
                f"Monnify HTTP {response.status_code}: {message}"
            )

        if not data.get("requestSuccessful"):
            raise RuntimeError(
                data.get(
                    "responseMessage",
                    "Unable to retrieve Monnify transfer status.",
                )
            )

        response_body = data.get(
            "responseBody"
        )

        if not response_body:
            raise RuntimeError(
                "Monnify returned an empty transfer status response."
            )

        return response_body

    def get_banks(self) -> list[dict]:
        """
        Retrieve the banks supported by Monnify.

        Uses Monnify's Get Banks API so the Flutter client does not
        need to maintain a hardcoded Nigerian bank list.
        """

        token = self.client.authenticate()

        url = (
            f"{settings.MONNIFY_BASE_URL.rstrip('/')}"
            "/api/v1/banks"
        )

        try:
            response = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Unable to connect to Monnify bank service."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Monnify returned an invalid bank-list response."
            ) from exc

        if response.is_error:
            message = data.get(
                "responseMessage",
                "Monnify bank-list request failed.",
            )

            raise RuntimeError(
                f"Monnify HTTP {response.status_code}: {message}"
            )

        if not data.get("requestSuccessful"):
            raise RuntimeError(
                data.get(
                    "responseMessage",
                    "Unable to retrieve Monnify banks.",
                )
            )

        response_body = data.get("responseBody")

        if not response_body:
            raise RuntimeError(
                "Monnify returned an empty bank-list response."
            )

        if not isinstance(response_body, list):
            raise RuntimeError(
                "Monnify returned an invalid bank-list format."
            )

        return response_body    