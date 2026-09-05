import argparse
import getpass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.features.identity.models import User
from app.features.identity.service import normalize_email
from app.platform.database import SessionLocal
from app.platform.security import hash_password


def create_admin(email: str) -> None:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")

    user = User(
        email_normalized=normalize_email(email),
        password_hash=hash_password(password),
        role="admin",
        approval_status="approved",
        approved_at=datetime.now(UTC),
    )

    with SessionLocal() as db:
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise SystemExit("A user with this email already exists.") from exc

    print(f"Created administrator: {user.email_normalized}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Competition Analysis backend CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    admin_parser = subparsers.add_parser("create-admin")
    admin_parser.add_argument("email")

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin(args.email)


if __name__ == "__main__":
    main()
