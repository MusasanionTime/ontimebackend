
from typing import Any
from decimal import Decimal, InvalidOperation

from app.changenow.client import ChangeNOWClient


class ChangeNOWService:
    """Business logic for ChangeNOW cryptocurrency exchanges."""

    TERMINAL_STATUSES = {
        "finished",
        "failed",
        "refunded",
        "expired",
    }

    STATUS_ORDER = {
        "waiting": 0,
        "confirming": 1,
        "exchanging": 2,
        "sending": 3,
        "finished": 4,
    }

    STATUS_ALIASES = {
        "new": "waiting",
        "waiting": "waiting",
        "confirming": "confirming",
        "exchanging": "exchanging",
        "sending": "sending",
        "finished": "finished",
        "complete": "finished",
        "completed": "finished",
        "success": "finished",
        "failed": "failed",
        "failure": "failed",
        "refunded": "refunded",
        "expired": "expired",
        "hold": "hold",
        "on_hold": "hold",
    }

    def __init__(self) -> None:
        self.client = ChangeNOWClient()

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _currency_matches(
        currency: dict[str, Any],
        ticker: str,
        network: str | None,
    ) -> bool:
        if not isinstance(currency, dict):
            return False

        if ChangeNOWService._normalize_text(
            currency.get("ticker")
        ) != ticker:
            return False

        if network and ChangeNOWService._normalize_text(
            currency.get("network")
        ) != network:
            return False

        return True

    def get_currencies(self) -> list[dict[str, Any]]:
        """Retrieve the available ChangeNOW currency catalogue."""
        currencies = self.client.get_available_currencies()

        if not isinstance(currencies, list):
            raise RuntimeError(
                "ChangeNOW returned an invalid currencies response."
            )

        return currencies

    def validate_currency_pair(
        self,
        *,
        from_currency: str,
        to_currency: str,
        from_network: str | None = None,
        to_network: str | None = None,
    ) -> dict[str, Any]:
        """Validate source sell support and destination buy support."""
        source_ticker = self._normalize_text(from_currency)
        destination_ticker = self._normalize_text(to_currency)
        source_network = self._normalize_text(from_network) or None
        destination_network = self._normalize_text(to_network) or None

        if not source_ticker:
            raise ValueError("Source currency is required.")

        if not destination_ticker:
            raise ValueError("Destination currency is required.")

        currencies = self.get_currencies()

        source_matches = [
            currency
            for currency in currencies
            if self._currency_matches(
                currency,
                source_ticker,
                source_network,
            )
            and currency.get("sell") is True
        ]

        destination_matches = [
            currency
            for currency in currencies
            if self._currency_matches(
                currency,
                destination_ticker,
                destination_network,
            )
            and currency.get("buy") is True
        ]

        if not source_matches:
            raise ValueError(
                "Unsupported source currency/network: "
                f"{source_ticker}/{source_network or 'default'}"
            )

        if not destination_matches:
            raise ValueError(
                "Unsupported destination currency/network: "
                f"{destination_ticker}/"
                f"{destination_network or 'default'}"
            )

        return {
            "valid": True,
            "from": source_matches[0],
            "to": destination_matches[0],
        }

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
    ) -> dict[str, Any]:
        """Validate input and submit an exchange request."""
        if not address or not address.strip():
            raise ValueError("Destination address is required.")

        if not from_amount or not from_amount.strip():
            raise ValueError("Source amount is required.")

        try:
            amount = Decimal(from_amount.strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                "Source amount must be a valid positive number."
            ) from exc

        if not amount.is_finite() or amount <= 0:
            raise ValueError(
                "Source amount must be a finite number greater than zero."
            )

        normalized_flow = self._normalize_text(flow)
        normalized_type = self._normalize_text(exchange_type)

        if normalized_flow not in {"standard", "fixed-rate"}:
            raise ValueError(
                "Unsupported flow. Use 'standard' or 'fixed-rate'."
            )

        if normalized_type not in {"direct", "reverse"}:
            raise ValueError(
                "Unsupported exchange type. Use 'direct' or 'reverse'."
            )

        self.validate_currency_pair(
            from_currency=from_currency,
            to_currency=to_currency,
            from_network=from_network,
            to_network=to_network,
        )

        return self.client.create_exchange(
            from_currency=from_currency.strip().lower(),
            to_currency=to_currency.strip().lower(),
            from_amount=from_amount.strip(),
            address=address.strip(),
            from_network=from_network,
            to_network=to_network,
            extra_id=extra_id,
            refund_address=refund_address,
            refund_extra_id=refund_extra_id,
            user_id=user_id,
            contact_email=contact_email,
            source=source,
            flow=normalized_flow,
            exchange_type=normalized_type,
            rate_id=rate_id,
        )

    def get_exchange_status(
        self,
        transaction_id: str,
    ) -> dict[str, Any]:
        """Retrieve exchange details from ChangeNOW."""
        if not transaction_id or not transaction_id.strip():
            raise ValueError("Transaction ID is required.")

        return self.client.get_exchange_status(transaction_id.strip())

    @classmethod
    def normalize_status(cls, status: str | None) -> str:
        """Normalize provider status names."""
        normalized = cls._normalize_text(status)

        if not normalized:
            return "unknown"

        return cls.STATUS_ALIASES.get(normalized, normalized)

    def is_valid_status_transition(
        self,
        current_status: str | None,
        new_status: str | None,
    ) -> bool:
        """Reject backward transitions and changes to terminal states."""
        if not new_status or not new_status.strip():
            return False

        next_status = self.normalize_status(new_status)

        if next_status == "unknown":
            return False

        if not current_status or not current_status.strip():
            return True

        previous_status = self.normalize_status(current_status)

        if previous_status == next_status:
            return True

        if previous_status in self.TERMINAL_STATUSES:
            return False

        if next_status in {"failed", "refunded", "expired"}:
            return True

        if next_status == "hold":
            return previous_status != "hold"

        if previous_status == "hold":
            return next_status in self.STATUS_ORDER

        if (
            previous_status in self.STATUS_ORDER
            and next_status in self.STATUS_ORDER
        ):
            return (
                self.STATUS_ORDER[next_status]
                >= self.STATUS_ORDER[previous_status]
            )

        return False
