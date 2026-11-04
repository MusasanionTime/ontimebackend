from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class WithdrawalRequest(BaseModel):
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        description="Withdrawal amount in NGN",
    )

    bank_account_id: str = Field(
        ...,
        min_length=1,
        description="Saved withdrawal bank account ID",
    )

    transaction_pin: str = Field(
        ...,
        min_length=4,
        max_length=4,
        description="4-digit transaction PIN",
    )

    narration: str | None = Field(
        default=None,
        max_length=200,
        description="Optional withdrawal narration",
    )

    @field_validator("transaction_pin")
    @classmethod
    def validate_transaction_pin(
        cls,
        value: str,
    ) -> str:
        if not value.isdigit():
            raise ValueError(
                "Transaction PIN must contain exactly 4 digits."
            )

        return value


class WithdrawalResponse(BaseModel):
    success: bool
    message: str
    data: dict