"""
> Why: Hash passwords and issue/validate signed bearer access tokens.
> Throughput: Password hashing is intentionally CPU-bound; token operations are local.
> Dependencies: pwdlib Argon2 and PyJWT.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Return a one-way Argon2 password verifier."""
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    """Check a password against its encoded verifier."""
    return password_hash.verify(password, encoded_hash)


def create_access_token(user_id: UUID, settings: Settings) -> str:
    """Issue a short-lived access token for the authenticated account."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> UUID:
    """Validate token signature/expiry and return its user identifier."""
    claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    subject = claims.get("sub")
    if not isinstance(subject, str):
        raise jwt.InvalidTokenError("Token subject is missing")
    try:
        return UUID(subject)
    except ValueError as exc:
        raise jwt.InvalidTokenError("Token subject is invalid") from exc
