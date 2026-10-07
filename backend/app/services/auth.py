import hmac
import secrets
from datetime import timedelta
import jwt
from sqlalchemy import select
from app.models import User, Challenge, RefreshSession, utcnow
from app.repositories.store import Users, Sessions, audit
from app.core.security import passwords, DUMMY_HASH, digest, code_digest, access_token
from app.core.errors import AppError
from app.schemas import Tokens, UserOut


class AuthService:
    def __init__(self, db, settings, mailer):
        self.db, self.settings, self.mailer = db, settings, mailer
        self.users, self.sessions = Users(db), Sessions(db)

    def register(self, data):
        if self.users.by_email(str(data.email)):
            raise AppError(409, "Пользователь с этой почтой уже существует")
        user = User(
            name=data.name,
            email=str(data.email).lower(),
            password_hash=passwords.hash(data.password),
            role=data.role,
        )
        try:
            self.db.add(user)
            self.db.flush()
            challenge = self.challenge(user)
            audit(self.db, user.id, "register", user.id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return challenge

    def challenge(self, user):
        cid, code = secrets.token_urlsafe(24), f"{secrets.randbelow(1000000):06d}"
        # Invalidate older challenges: only the most recently issued code is accepted.
        for previous in self.db.scalars(
            select(Challenge).where(Challenge.user_id == user.id, Challenge.used.is_(False))
        ):
            previous.used = True
        self.db.add(
            Challenge(
                id=cid,
                user_id=user.id,
                code_hash=code_digest(self.settings.secret_key, cid, code),
                expires_at=utcnow() + timedelta(minutes=10),
            )
        )
        delivery = self.mailer.send_code(user.email, cid, code)
        return {"challenge_id": cid, "expires_in": 600, "delivery": delivery}

    def login(self, data):
        user = self.users.by_email(str(data.email))
        try:
            valid = passwords.verify(data.password, user.password_hash if user else DUMMY_HASH)
        except Exception:
            valid = False
        if not user or not valid or not user.active:
            raise AppError(401, "Неверная почта или пароль")
        try:
            challenge = self.challenge(user)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return challenge

    def issue(self, user, family=None):
        token, family = secrets.token_urlsafe(48), family or secrets.token_urlsafe(24)
        self.db.add(
            RefreshSession(
                user_id=user.id,
                family=family,
                token_hash=digest(token),
                expires_at=utcnow() + timedelta(days=self.settings.refresh_days),
            )
        )
        return Tokens(
            access_token=access_token(self.settings, user, family),
            refresh_token=token,
            expires_in=self.settings.access_minutes * 60,
            user=UserOut.model_validate(user),
        )

    def verify(self, data):
        row = self.db.get(Challenge, data.challenge_id)
        if not row or row.used or row.expires_at < utcnow() or row.attempts >= 5:
            raise AppError(401, "Код недействителен или истёк")
        row.attempts += 1
        if not hmac.compare_digest(
            row.code_hash, code_digest(self.settings.secret_key, row.id, data.code)
        ):
            self.db.commit()
            raise AppError(401, "Неверный код")
        user = self.users.get(row.user_id)
        if not user or not user.active:
            raise AppError(401, "Учётная запись недоступна")
        row.used = True
        result = self.issue(user)
        audit(self.db, user.id, "login", user.id)
        self.db.commit()
        return result

    def refresh(self, token):
        row = self.sessions.by_hash(digest(token))
        if not row:
            raise AppError(401, "Сессия недействительна")
        if row.used:
            self.sessions.revoke(row.family)
            self.db.commit()
            raise AppError(401, "Повторное использование токена: войдите заново")
        if row.revoked or row.expires_at < utcnow():
            raise AppError(401, "Сессия истекла")
        user = self.users.get(row.user_id)
        if not user or not user.active:
            raise AppError(401, "Учётная запись недоступна")
        row.used = True
        result = self.issue(user, row.family)
        self.db.commit()
        return result

    def authenticate(self, token):
        try:
            payload = jwt.decode(
                token,
                self.settings.secret_key,
                algorithms=["HS256"],
                audience="todaygo-client",
                issuer="todaygo",
                options={"require": ["exp", "iat", "sub", "sid", "type"]},
            )
            if payload["type"] != "access":
                raise ValueError()
            user = self.users.get(int(payload["sub"]))
            sessions = self.sessions.family(payload["sid"])
            if (
                not user
                or not user.active
                or not any(
                    not s.revoked
                    and not s.used
                    and s.expires_at > utcnow()
                    and s.user_id == user.id
                    for s in sessions
                )
            ):
                raise ValueError()
            return user, payload["sid"]
        except (jwt.PyJWTError, ValueError, KeyError):
            raise AppError(401, "Требуется авторизация") from None

    def logout(self, family, user):
        self.sessions.revoke(family)
        audit(self.db, user.id, "logout", user.id)
        self.db.commit()
