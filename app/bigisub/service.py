
from typing import Any
from decimal import Decimal, InvalidOperation

from app.bigisub.client import BigisubClient


class BigisubService:
    """
    Business logic layer for BigiSub provider operations.

    Provider requests are delegated to BigisubClient.

    The API route/service layer must handle:
    - Customer transaction PIN verification
    - Wallet balance validation
    - Wallet fund reservation
    - Transaction records
    - Provider response reconciliation
    - Refunds when explicitly appropriate

    Provider PINs must never be accepted from customers.
    """

    def __init__(self) -> None:
        self.client = BigisubClient()

    # ============================================================
    # LOGIN
    # ============================================================

    def login(
        self,
        email_or_username: str,
        password: str,
    ) -> dict[str, Any]:
        return self.client.login(
            email_or_username=email_or_username,
            password=password,
        )

    # ============================================================
    # BIGISUB WALLET BALANCE
    # ============================================================

    def get_wallet_balance(self) -> dict[str, Any]:
        return self.client.get_wallet_balance()

    # ============================================================
    # AIRTIME PURCHASE
    # ============================================================

    def purchase_airtime(
        self,
        network: int,
        phone_number: str,
        amount: str,
        airtime_type: str = "vtu",
    ) -> dict[str, Any]:
        """
        Purchase airtime using the original BigiSub VTU API.

        The provider PIN is obtained by BigisubClient from
        BIGISUB_PROVIDER_PIN in backend settings.

        The customer's transaction PIN must be verified
        separately by the authenticated API route.

        Never retry a purchase automatically after an
        uncertain provider outcome.
        """

        if (
            isinstance(network, bool)
            or not isinstance(network, int)
            or network <= 0
        ):
            raise ValueError(
                "A valid BigiSub network ID is required."
            )

        if not isinstance(phone_number, str):
            raise ValueError(
                "Phone number must be a string."
            )

        normalized_phone = phone_number.strip()

        if not normalized_phone:
            raise ValueError(
                "Customer phone number is required."
            )

        if not isinstance(airtime_type, str):
            raise ValueError(
                "Airtime type must be a string."
            )

        normalized_type = airtime_type.strip().lower()

        if normalized_type != "vtu":
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

        return self.client.purchase_airtime(
            network=network,
            phone_number=normalized_phone,
            amount=str(numeric_amount),
            airtime_type=normalized_type,
        )

    # ============================================================
    # DATA
    # ============================================================

    def get_data_plans(self) -> dict[str, Any]:
        return self.client.get_data_plans()

    def purchase_data(
        self,
        network: int,
        plan: int,
        phone_number: str,
        ported_number: bool = False,
    ) -> dict[str, Any]:
        return self.client.purchase_data(
            network=network,
            plan=plan,
            phone_number=phone_number,
            ported_number=ported_number,
        )

    # ============================================================
    # CABLE TV
    # ============================================================

    def get_cable_plans(self) -> dict[str, Any]:
        return self.client.get_cable_plans()

    # ============================================================
    # RECHARGE PIN
    # ============================================================

    def get_recharge_pin_plans(self) -> dict[str, Any]:
        return self.client.get_recharge_pin_plans()

    # ============================================================
    # RESULT CHECKER PRICES
    # ============================================================

    def get_result_checker_prices(self) -> dict[str, Any]:
        """Retrieve live Result Checker catalogue prices."""
        return self.client.get_result_checker_prices()

    # ============================================================
    # RESULT CHECKER PURCHASE
    # ============================================================

    def purchase_result_checker(
        self,
        exam: str,
        quantity: int,
    ) -> dict[str, Any]:
        """
        Purchase Result Checker PINs through BigiSub.

        Provider PIN is managed securely by the client.

        The caller must verify the customer's transaction PIN,
        retrieve live pricing, reserve wallet funds and record
        the transaction before making this provider request.
        """

        if not isinstance(exam, str) or not exam.strip():
            raise ValueError(
                "Examination type is required."
            )

        normalized_exam = exam.strip().upper()

        if normalized_exam not in {"WAEC", "NECO", "NABTEB"}:
            raise ValueError(
                "Unsupported examination type."
            )

        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise ValueError(
                "Quantity must be a valid integer."
            )

        if not 1 <= quantity <= 20:
            raise ValueError(
                "Quantity must be between 1 and 20."
            )

        return self.client.purchase_result_checker(
            exam=normalized_exam,
            quantity=quantity,
        )

    # ============================================================
    # SMILE INTERNET
    # ============================================================

    def get_smile_plans(self) -> dict[str, Any]:
        return self.client.get_smile_plans()

    # ============================================================
    # BETTING
    # ============================================================

    def get_betting_billers(self) -> dict[str, Any]:
        return self.client.get_betting_billers()

    # ============================================================
    # ELECTRICITY PROVIDERS
    # ============================================================

    def get_electricity_providers(self) -> dict[str, Any]:
        """Get supported BigiSub electricity providers."""
        return self.client.get_electricity_providers()

    # ============================================================
    # ELECTRICITY METER VERIFICATION
    # ============================================================

    def verify_electricity_meter(
        self,
        company: str,
        meter_no: str,
        meter_type: str,
    ) -> dict[str, Any]:
        """Verify a customer's electricity meter."""

        return self.client.verify_electricity_meter(
            company=company,
            meter_no=meter_no,
            meter_type=meter_type,
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
        """
        Purchase electricity using verified customer details.

        The caller is responsible for:
        - Verifying the electricity meter
        - Checking the customer's transaction PIN
        - Reserving the correct wallet amount
        - Recording the transaction
        - Reconciling uncertain provider outcomes

        Never retry an uncertain purchase automatically.
        """

        return self.client.purchase_electricity(
            company=company,
            meter_no=meter_no,
            meter_type=meter_type,
            phone_number=phone_number,
            amount=amount,
            customer_name=customer_name,
        )
