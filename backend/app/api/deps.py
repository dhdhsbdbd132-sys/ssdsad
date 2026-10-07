from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from app.services.auth import AuthService
from app.core.errors import AppError

bearer = OAuth2PasswordBearer(
    tokenUrl="/api/auth/token",
    auto_error=False,
    scopes={
        "events:read": "Просмотр событий",
        "events:write": "Управление событиями",
        "admin": "Управление пользователями",
    },
)


def get_db(request: Request):
    with request.app.state.db.sessions() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise


def auth_service(request: Request, db=Depends(get_db)):
    return AuthService(db, request.app.state.settings, request.app.state.mailer)


def optional_identity(token=Depends(bearer), service=Depends(auth_service)):
    return service.authenticate(token) if token else None


def identity(value=Depends(optional_identity)):
    if not value:
        raise AppError(401, "Требуется авторизация")
    return value


def current_user(value=Depends(identity)):
    return value[0]


def admin(user=Depends(current_user)):
    if user.role != "admin":
        raise AppError(403, "Требуются права администратора")
    return user
