"""OIDC Authorization Code + PKCE for a native client, with one-time polling."""

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlencode
import httpx
import jwt
from app.models import OAuthAttempt, User, utcnow
from app.core.security import digest, passwords
from app.core.errors import AppError
from app.repositories.store import Users, audit
from app.services.auth import AuthService


class OAuthService:
    def __init__(self, db, settings, mailer):
        self.db, self.settings, self.mailer = db, settings, mailer

    def metadata(self):
        if not self.settings.oauth_client_id:
            raise AppError(503, "OAuth не настроен администратором")
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                response = client.get(self.settings.oauth_discovery_url)
                response.raise_for_status()
                data = response.json()
            if data["issuer"] != self.settings.oauth_issuer:
                raise ValueError()
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                if not data[key].startswith("https://"):
                    raise ValueError()
            return data
        except (httpx.HTTPError, ValueError, KeyError):
            raise AppError(502, "OAuth-провайдер недоступен") from None

    def start(self):
        metadata = self.metadata()
        state, poll, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        self.db.add(
            OAuthAttempt(
                id=state,
                poll_hash=digest(poll),
                verifier=verifier,
                nonce=nonce,
                expires_at=utcnow() + timedelta(minutes=10),
            )
        )
        self.db.commit()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        params = {
            "response_type": "code",
            "client_id": self.settings.oauth_client_id,
            "redirect_uri": self.settings.oauth_redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return {
            "authorization_url": metadata["authorization_endpoint"] + "?" + urlencode(params),
            "state": state,
            "poll_key": poll,
        }

    def callback(self, state, code):
        attempt = self.db.get(OAuthAttempt, state)
        if not attempt or attempt.used or attempt.completed or attempt.expires_at < utcnow():
            raise AppError(400, "OAuth-сессия недействительна")
        metadata = self.metadata()
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    metadata["token_endpoint"],
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "client_id": self.settings.oauth_client_id,
                        "client_secret": self.settings.oauth_client_secret,
                        "redirect_uri": self.settings.oauth_redirect_uri,
                        "code_verifier": attempt.verifier,
                    },
                )
                response.raise_for_status()
                id_token = response.json()["id_token"]
                jwks = client.get(metadata["jwks_uri"])
                jwks.raise_for_status()
                header = jwt.get_unverified_header(id_token)
                key_data = next(
                    key for key in jwks.json()["keys"] if key.get("kid") == header.get("kid")
                )
                if key_data.get("kty") != "RSA":
                    raise ValueError()
                key = jwt.PyJWK.from_dict(key_data).key
                claims = jwt.decode(
                    id_token,
                    key,
                    algorithms=["RS256"],
                    issuer=self.settings.oauth_issuer,
                    audience=self.settings.oauth_client_id,
                    options={"require": ["exp", "iat", "sub", "nonce", "email", "email_verified"]},
                )
                if (
                    not hmac.compare_digest(claims["nonce"], attempt.nonce)
                    or claims["email_verified"] is not True
                ):
                    raise ValueError()
        except (httpx.HTTPError, jwt.PyJWTError, KeyError, ValueError, StopIteration):
            raise AppError(401, "Не удалось подтвердить OAuth-вход") from None
        # Never silently link an OAuth identity to an existing password account.
        # A verified provider email still requires a fresh code sent to that mailbox.
        from pydantic import TypeAdapter, EmailStr

        try:
            email = str(TypeAdapter(EmailStr).validate_python(claims["email"])).lower()
        except ValueError:
            raise AppError(401, "Провайдер не вернул корректную почту") from None
        user = Users(self.db).by_email(email)
        if not user:
            user = User(
                name=str(claims.get("name", "Участник"))[:80],
                email=email,
                password_hash=passwords.hash(secrets.token_urlsafe(64)),
                role="attendee",
            )
            self.db.add(user)
            self.db.flush()
        if not user.active:
            raise AppError(401, "Учётная запись недоступна")
        challenge = AuthService(self.db, self.settings, self.mailer).challenge(user)
        attempt.challenge_id, attempt.completed = challenge["challenge_id"], True
        # The verifier is no longer needed after a successful exchange.
        attempt.verifier = ""
        audit(self.db, user.id, "oauth.challenge", user.id)
        self.db.commit()

    def poll(self, state, poll_key):
        attempt = self.db.get(OAuthAttempt, state)
        if (
            not attempt
            or attempt.used
            or attempt.expires_at < utcnow()
            or not hmac.compare_digest(attempt.poll_hash, digest(poll_key))
        ):
            raise AppError(401, "OAuth-сессия недействительна")
        if not attempt.completed:
            return {"status": "pending"}
        attempt.used = True
        self.db.commit()
        return {"status": "complete", "challenge_id": attempt.challenge_id}
