import hashlib
import hmac
from datetime import timedelta
import jwt
from pwdlib import PasswordHash
from app.models import utcnow

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("constant-time-placeholder-not-an-account")


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def code_digest(secret: str, challenge: str, code: str):
    return hmac.new(secret.encode(), f"{challenge}:{code}".encode(), hashlib.sha256).hexdigest()


def access_token(settings, user, family):
    now = utcnow()
    return jwt.encode(
        {
            "sub": str(user.id),
            "sid": family,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_minutes),
            "iss": "todaygo",
            "aud": "todaygo-client",
        },
        settings.secret_key,
        algorithm="HS256",
    )
