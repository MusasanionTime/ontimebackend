from pydantic import BaseModel, Field, field_validator


class SetTransactionPinRequest(BaseModel):
    pin: str = Field(
        ...,
        min_length=4,
        max_length=4,
        description="4-digit transaction PIN",
    )

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("Transaction PIN must contain exactly 4 digits.")

        return value


class TransactionPinResponse(BaseModel):
    message: str
    pin_set: bool