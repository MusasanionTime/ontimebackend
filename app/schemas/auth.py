from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=30)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)

    referral_code: str | None = Field(default=None, max_length=30)


class RegisterResponse(BaseModel):
    id: str
    email: EmailStr
    wallet_currency: str
    wallet_number: str
    referral_code: str

    account_number: str | None = None
    bank_name: str | None = None
    bank_code: str | None = None

    message: str