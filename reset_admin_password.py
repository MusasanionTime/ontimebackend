from getpass import getpass

from sqlalchemy import select
from app.database.database import SessionLocal
from app.models.admin import Admin
from app.auth.security import hash_password

EMAIL = "admin@ontimedatasub.com"

password = getpass("Enter your NEW admin password: ")
confirmation = getpass("Confirm your NEW admin password: ")

if len(password) < 12:
    raise SystemExit("Password must contain at least 12 characters.")

if password != confirmation:
    raise SystemExit("Passwords do not match. No changes made.")

db = SessionLocal()

try:
    admin = db.scalar(
        select(Admin).where(Admin.email == EMAIL)
    )

    if admin is None:
        raise SystemExit(f"Admin account not found: {EMAIL}")

    admin.password_hash = hash_password(password)
    db.commit()

    print(f"Password reset successfully for {EMAIL}")
    print(f"Admin ID: {admin.id}")

except Exception:
    db.rollback()
    raise
finally:
    db.close()
