
import uuid

import httpx

from app.core.config import settings
from app.monnify.client import MonnifyClient


class MonnifyService:
    def __init__(self):
        self.client = MonnifyClient()

    # ---------------------------------------------------------
    # AUTHENTICATION
    # ---------------------------------------------------------

    def get_access_token(self) -> str:
        return self.client.authenticate()

    # ---------------------------------------------------------
    # INCOMING COLLECTION VERIFICATION
    # ---------------------------------------------------------

    def verify_collection_transaction(
        self,
        *,
        transaction_reference: str,
    ) -> dict:
        """
        Verify an incoming Monnify collection transaction.

        This is for customer payments, not disbursements.
        """

        if not transaction_reference or not transaction_reference.strip():
            raise ValueError("Transaction reference is required.")

        response = self.client.get(
            "/api/v2/merchant/transactions/query",
            params={
                "transactionReference": transaction_reference.strip()
            },
        )

        response_body = response.get("responseBody")

        if not isinstance(response_body, dict):
            raise RuntimeError(
                "Monnify returned an invalid collection verification response."
            )

        return response_body

    # ---------------------------------------------------------
    # RESERVED BANK ACCOUNT CREATION
    # ---------------------------------------------------------

    def create_reserved_account(
        self,
        *,
        account_name: str,
        customer_email: str,
        customer_name: str,
        account_reference: str | None = None,
        bvn: str | None = None,
        nin: str | None = None,
        get_all_available_banks: bool = True,
    ) -> dict:
        """
        Create a Monnify reserved bank account.

        Supports a caller-supplied account reference so the
        application can save the reference before contacting
        Monnify and safely reconcile uncertain requests.

        BVN and NIN are sent directly to Monnify.
        They are never persisted or logged by this service.
        """

        # Validate identity information.
        bvn = bvn.strip() if bvn else None
        nin = nin.strip() if nin else None

        if bool(bvn) == bool(nin):
            raise ValueError(
                "Provide exactly one of BVN or NIN."
            )

        if bvn and (not bvn.isdigit() or len(bvn) != 11):
            raise ValueError(
                "BVN must contain exactly 11 digits."
            )

        if nin and (not nin.isdigit() or len(nin) != 11):
            raise ValueError(
                "NIN must contain exactly 11 digits."
            )

        if not account_name or not account_name.strip():
            raise ValueError("Account name is required.")

        if not customer_email or not customer_email.strip():
            raise ValueError("Customer email is required.")

        if not customer_name or not customer_name.strip():
            raise ValueError("Customer name is required.")

        # Preserve a reference supplied by the application.
        # Generate an ONTIME reference only when none is supplied.
        if account_reference:
            account_reference = account_reference.strip()

            if not account_reference:
                raise ValueError(
                    "Account reference cannot be empty."
                )
        else:
            account_reference = (
                f"ONTIME-RA-{uuid.uuid4().hex[:20].upper()}"
            )

        if not settings.MONNIFY_CONTRACT_CODE:
            raise RuntimeError(
                "Monnify contract code is not configured."
            )

        payload = {
            "accountReference": account_reference,
            "accountName": account_name.strip(),
            "currencyCode": "NGN",
            "contractCode": settings.MONNIFY_CONTRACT_CODE,
            "customerEmail": customer_email.strip(),
            "customerName": customer_name.strip(),
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
                    "Accept": "application/json",
                },
                json=payload,
                timeout=30.0,
            )

        except httpx.RequestError as exc:
            # The request may have reached Monnify even if
            # the client did not receive a response.
            # The caller must reconcile using account_reference.
            raise RuntimeError(
                "Unable to confirm the Monnify reserved-account "
                "request. Reconciliation is required."
            ) from exc

        try:
            data = response.json()

        except ValueError as exc:
            raise RuntimeError(
                "Monnify returned an invalid reserved-account response. "
                "Reconciliation may be required."
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "Monnify returned an invalid reserved-account response."
            )

        if response.is_error:
            message = data.get(
                "responseMessage",
                "Monnify reserved-account request failed.",
            )

            raise RuntimeError(
                f"Monnify HTTP {response.status_code}: {message}"
            )

        if not data.get("requestSuccessful"):
            message = data.get(
                "responseMessage",
                "Monnify reserved-account creation failed.",
            )

            raise RuntimeError(str(message))

        response_body = data.get("responseBody")

        if not isinstance(response_body, dict):
            raise RuntimeError(
                "Monnify returned an invalid account response. "
                "Reconciliation is required."
            )

        # Do not assume account details exist merely because
        # requestSuccessful is true. The application endpoint
        # must validate the actual returned account information.
        return response_body

    # ---------------------------------------------------------
    # BANK ACCOUNT NAME ENQUIRY
    # ---------------------------------------------------------

    def validate_bank_account(
        self,
        *,
        account_number: str,
        bank_code: str,
    ) -> dict:
        """
        Verify a Nigerian bank account using Monnify Name Enquiry.
        """

        if not account_number or not account_number.strip():
            raise ValueError("Account number is required.")

        if not bank_code or not bank_code.strip():
            raise ValueError("Bank code is required.")

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
                    "accountNumber": account_number.strip(),
                    "bankCode": bank_code.strip(),
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
                "Monnify returned an invalid bank account response."
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

        response_body = data.get("responseBody")

        if not isinstance(response_body, dict):
            raise RuntimeError(
                "Monnify returned an invalid bank account response."
            )

        return response_body

    # ---------------------------------------------------------
    # SINGLE TRANSFER / WITHDRAWAL
    # ---------------------------------------------------------

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

        The destination account name must come from a successful
        Monnify Name Enquiry response.
        """

        if amount <= 0:
            raise ValueError(
                "Transfer amount must be greater than zero."
            )

        if not reference or not reference.strip():
            raise ValueError("Transfer reference is required.")

        if not narration or not narration.strip():
            raise ValueError("Transfer narration is required.")

        if not destination_bank_code or not destination_bank_code.strip():
            raise ValueError("Destination bank code is required.")

        if (
            not destination_account_number
            or not destination_account_number.strip()
        ):
            raise ValueError(
                "Destination account number is required."
            )

        if (
            not destination_account_name
            or not destination_account_name.strip()
        ):
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
            "reference": reference.strip(),
            "narration": narration.strip(),
            "destinationBankCode": destination_bank_code.strip(),
            "destinationAccountNumber": (
                destination_account_number.strip()
            ),
            "destinationAccountName": (
                destination_account_name.strip()
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

        response_body = data.get("responseBody")

        if not isinstance(response_body, dict):
            raise RuntimeError(
                "Monnify returned an invalid disbursement response."
            )

        return response_body

    # ---------------------------------------------------------
    # SINGLE TRANSFER STATUS
    # ---------------------------------------------------------

    def get_single_transfer_status(
        self,
        *,
        reference: str,
    ) -> dict:
        """
        Get the current status of a Monnify single transfer.

        This endpoint is for outgoing disbursements.
        It is not used to verify incoming customer collections.
        """

        if not reference or not reference.strip():
            raise ValueError("Transfer reference is required.")

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
                    "reference": reference.strip(),
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

        response_body = data.get("responseBody")

        if not isinstance(response_body, dict):
            raise RuntimeError(
                "Monnify returned an invalid transfer status response."
            )

        return response_body

    # ---------------------------------------------------------
    # DYNAMIC BANK LIST
    # ---------------------------------------------------------

    def get_banks(self) -> list[dict]:
        """
        Retrieve banks supported by Monnify.

        Flutter should use this endpoint rather than maintaining
        a hardcoded Nigerian bank list.
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

        if not isinstance(response_body, list):
            raise RuntimeError(
                "Monnify returned an invalid bank-list format."
            )

        return response_body
