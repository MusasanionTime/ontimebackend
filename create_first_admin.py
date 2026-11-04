from getpass import getpass
from sqlalchemy import select
from app.database.database import SessionLocal
from app.models.admin import Admin
from app.auth.security import hash_password

email = input("Admin email: ").strip().lower()
password = getpass("Create admin password (hidden): ")

if not email or "@" not in email:
    raise SystemExit("Enter a valid email address.")

if len(password) < 12:
    raise SystemExit("Use at least 12 characters for the password.")

db = SessionLocal()
try:
    existing = db.scalar(select(Admin).where(Admin.email == email))
    if existing:
        raise SystemExit("An admin with this email already exists.")

    admin = Admin(
        email=email,
        password_hash=hash_password(password),
        first_name="System",
        last_name="Administrator",
        role="super_admin",
        is_active=True,
    )
    db.add(admin)
    db.commit()
    print("Admin created successfully.")
    print("Admin ID:", admin.id)
    print("Admin email:", admin.email)
except Exception:
    db.rollback()
    raise
finally:
    db.close()
