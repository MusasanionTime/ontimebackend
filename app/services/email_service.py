import smtplib
from email.message import EmailMessage

from app.core.config import settings


def send_password_reset_email(
    recipient_email: str,
    reset_token: str,
) -> None:
    reset_url = (
        f"{settings.FRONTEND_URL.rstrip('/')}"
        f"/reset-password?token={reset_token}"
    )

    message = EmailMessage()

    message["Subject"] = "Reset your ONTIME SUBDATA LTD password"
    message["From"] = (
        f"{settings.SMTP_FROM_NAME} "
        f"<{settings.SMTP_FROM_EMAIL}>"
    )
    message["To"] = recipient_email

    message.set_content(
        f"""Hello,

We received a request to reset your ONTIME SUBDATA LTD password.

Use the link below to create a new password:

{reset_url}

This link expires in 30 minutes and can only be used once.

If you did not request a password reset, you can safely ignore this email.

Regards,
ONTIME SUBDATA LTD
"""
    )

    with smtplib.SMTP(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        timeout=30,
    ) as smtp:
        smtp.starttls()

        smtp.login(
            settings.SMTP_USERNAME,
            settings.SMTP_PASSWORD,
        )

        smtp.send_message(message)