import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def random_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def csrf_token(session_token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), session_token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_csrf(session_token: str, submitted_token: str, secret: str) -> bool:
    expected = csrf_token(session_token, secret)
    return hmac.compare_digest(expected, submitted_token)
