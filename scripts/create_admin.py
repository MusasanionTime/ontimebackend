import getpass

from sqlalchemy import select

from app.auth.security import hash_password
from app.database.database import SessionLocal
from app.models.admin import Admin


def main():
    print("=== ONTIME SUBDATA LTD Admin Creation ===")

    email = input("Admin email: ").strip().lower()
    first_name = input("First name: ").strip() or None
    last_name = input("Last name: ").strip() or None

    password = getpass.getpass("Admin password: ")
    confirm_password = getpass.getpass("Confirm password: ")

    if password != confirm_password:
        print("Error: passwords do not match.")
        return

    if len(password) < 8:
        print("Error: password must be at least 8 characters.")
        return

    db = SessionLocal()

    try:
        existing_admin = db.scalar(
            select(Admin).where(Admin.email == email)
        )

        if existing_admin:
            print("Error: an admin with this email already exists.")
            return

        admin = Admin(
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role="super_admin",
            is_active=True,
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print()
        print("Admin created successfully.")
        print(f"ID: {admin.id}")
        print(f"Email: {admin.email}")
        print(f"Role: {admin.role}")
        print(f"Active: {admin.is_active}")

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()