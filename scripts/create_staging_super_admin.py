from getpass import getpass
from sqlalchemy import select

from app.database.database import get_db
from app.models.admin import Admin
from app.auth.security import hash_password

EXPECTED_DATABASE = "ontime_commission_staging"
EXPECTED_HOST = "ep-proud-hall-za9px571.c-2.eu-west-2.aws.neon.tech"

db_generator = get_db()
db = next(db_generator)

try:
    url = db.get_bind().url

    if url.database != EXPECTED_DATABASE or url.host != EXPECTED_HOST:
        raise RuntimeError("SAFETY STOP: Wrong database.")

    print("\nONTIME SUBDATA LTD - Super Admin Setup")

    email = input("Admin email: ").strip().lower()
    first_name = input("First name: ").strip()
    last_name = input("Last name: ").strip()

    if not email or "@" not in email:
        raise ValueError("Invalid email address.")

    existing = db.scalar(select(Admin).where(Admin.email == email))
    if existing:
        raise ValueError("This email already exists.")

    existing_super_admin = db.scalar(
        select(Admin.id).where(Admin.role == "super_admin").limit(1)
    )
    if existing_super_admin:
        raise ValueError("A Super Admin already exists.")

    password = getpass("New password: ")
    confirmation = getpass("Confirm password: ")

    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")

    if password != confirmation:
        raise ValueError("Passwords do not match.")

    admin = Admin(
        email=email,
        password_hash=hash_password(password),
        first_name=first_name or None,
        last_name=last_name or None,
        role="super_admin",
        is_active=True,
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)

    print("\nSUCCESS: Super Admin created.")
    print("Email:", admin.email)
    print("Role:", admin.role)
    print("Active:", admin.is_active)
    print("Database:", url.database)

except Exception:
    db.rollback()
    raise

finally:
    db.close()
    db_generator.close()
