import hashlib
import hmac
from decimal import Decimal

from app.core.config import settings

KoboAmount = int


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    secret = settings.TOPIFY_WEBHOOK_SECRET or ""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def parse_kobo(value: object, *, allow_zero: bool = False) -> KoboAmount:
    """Accept only JSON integers; bools and decimal/string amounts are invalid."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Topify amount must be an integer number of kobo.")  # noqa: TRY004
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError("Topify amount must be positive.")
    if value > 99_999_999_999_999_999_999:
        raise ValueError("Topify amount exceeds the wallet ledger limit.")
    return value


def kobo_to_naira(value: KoboAmount) -> Decimal:
    return (Decimal(value) / Decimal(100)).quantize(Decimal("0.01"))


def topify_transaction_key(provider_reference: str) -> str:
    digest = hashlib.sha256(provider_reference.encode("utf-8")).hexdigest().upper()
    return f"TPY-{digest}"


def safe_event_metadata(event_type: str, data: dict) -> dict:
    """Store allowlisted non-PII audit fields, never the raw webhook payload."""
    metadata = {"event": event_type}
    for source, target in (
        ("amount", "amount_kobo"),
        ("fee", "fee_kobo"),
        ("currency", "currency"),
        ("status", "provider_status"),
        ("provider", "provider"),
        ("paid_at", "paid_at"),
    ):
        value = data.get(source)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            metadata[target] = value
    customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}
    customer_code = customer.get("customer_code") or data.get("customer_code")
    if isinstance(customer_code, str) and customer_code:
        metadata["customer_code"] = customer_code[:100]
    return metadata
