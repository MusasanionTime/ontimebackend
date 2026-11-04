from decimal import Decimal

from pydantic import BaseModel, Field


class ChangeNOWExchangeCreate(BaseModel):
    from_currency: str = Field(
        min_length=2,
        max_length=50,
    )

    to_currency: str = Field(
        min_length=2,
        max_length=50,
    )

    from_amount: Decimal = Field(
        gt=0,
    )

    address: str = Field(
        min_length=10,
        max_length=500,
    )

    from_network: str | None = Field(
        default=None,
        max_length=100,
    )

    to_network: str | None = Field(
        default=None,
        max_length=100,
    )

    extra_id: str | None = Field(
        default=None,
        max_length=255,
    )

    refund_address: str | None = Field(
        default=None,
        max_length=500,
    )

    refund_extra_id: str | None = Field(
        default=None,
        max_length=255,
    )

    flow: str = Field(
        default="standard",
        max_length=50,
    )

    exchange_type: str = Field(
        default="direct",
        max_length=50,
    )

    rate_id: str | None = Field(
        default=None,
        max_length=255,
    )


class ChangeNOWPairValidationResponse(BaseModel):
    valid: bool
    from_currency: str
    to_currency: str
    from_network: str | None
    to_network: str | None


class ChangeNOWExchangeResponse(BaseModel):
    id: str

    provider: str

    provider_transaction_id: str | None

    from_currency: str
    to_currency: str

    from_network: str | None
    to_network: str | None

    from_amount: Decimal
    to_amount: Decimal | None

    destination_address: str
    refund_address: str | None

    deposit_address: str | None
    deposit_extra_id: str | None

    status: str

    rate_id: str | None

    created_at: str
    updated_at: str