import argparse
import getpass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.features.identity.models import User
from app.features.identity.service import normalize_identity
from app.platform.database import SessionLocal
from app.platform.security import hash_password


def create_admin(identity: str) -> None:
    identity = normalize_identity(identity)
    if len(identity) < 4 or len(identity) > 64:
        raise SystemExit("Identity must contain between 4 and 64 characters.")

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")

    user = User(
        identity_normalized=identity,
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
            raise SystemExit("A user with this identity already exists.") from exc

    print(f"Created administrator: {user.identity_normalized}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Competition Analysis backend CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    admin_parser = subparsers.add_parser("create-admin")
    admin_parser.add_argument("identity")

    args = parser.parse_args()

    if args.command == "create-admin":
        create_admin(args.identity)


if __name__ == "__main__":
    main()
