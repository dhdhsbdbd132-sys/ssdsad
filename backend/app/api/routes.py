from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Response
from fastapi.security import OAuth2PasswordRequestForm
from app.api.deps import get_db, auth_service, optional_identity, identity, current_user, admin
from app.schemas import (
    Register,
    Login,
    ChallengeOut,
    Verify,
    Tokens,
    Refresh,
    UserOut,
    EventInput,
    EventPatch,
    EventOut,
    EventPage,
    Category,
    RoleUpdate,
    ErrorResponse,
)
from app.services.events import EventService
from app.services.users import UserService
from app.repositories.store import Users
from app.core.errors import AppError

router = APIRouter(
    prefix="/api",
    responses={
        code: {"model": ErrorResponse, "description": text}
        for code, text in {
            400: "Некорректный запрос",
            401: "Требуется вход",
            403: "Недостаточно прав",
            404: "Не найдено",
            409: "Конфликт данных",
            429: "Слишком много запросов",
            500: "Ошибка сервера",
            503: "Сервис не настроен",
        }.items()
    },
)


@router.get("/health", tags=["Система"])
def health(db=Depends(get_db)):
    from sqlalchemy import select

    db.execute(select(1))
    return {"status": "ok"}


@router.post("/auth/register", response_model=ChallengeOut, status_code=201, tags=["Авторизация"])
def register(data: Register, service=Depends(auth_service)):
    """Регистрация участника или организатора и отправка почтового кода."""
    return service.register(data)


@router.post("/auth/login", response_model=ChallengeOut, tags=["Авторизация"])
def login(data: Login, service=Depends(auth_service)):
    """Первый фактор: пароль. Токены выдаются только после второго фактора."""
    return service.login(data)


@router.post("/auth/token", response_model=Tokens, tags=["Авторизация"])
def oauth_token(form: OAuth2PasswordRequestForm = Depends(), service=Depends(auth_service)):
    """OAuth2 token endpoint: username=challenge_id, password=почтовый код.

    Сначала получите challenge через /auth/login. Swagger Authorize принимает
    challenge_id и шестизначный код вместо email и пароля. Повышение роли через scope запрещено.
    """
    if form.scopes:
        raise AppError(400, "Права назначаются сервером, параметр scope не поддерживается")
    from pydantic import ValidationError

    try:
        data = Verify(challenge_id=form.username, code=form.password)
    except ValidationError:
        raise AppError(400, "Укажите challenge_id и шестизначный почтовый код") from None
    return service.verify(data)


@router.post("/auth/verify", response_model=Tokens, tags=["Авторизация"])
def verify(data: Verify, service=Depends(auth_service)):
    return service.verify(data)


@router.post("/auth/refresh", response_model=Tokens, tags=["Авторизация"])
def refresh(data: Refresh, service=Depends(auth_service)):
    """Ротация одноразового refresh-токена. Повторное использование отзывает всю сессию."""
    return service.refresh(data.refresh_token)


@router.post("/auth/logout", status_code=204, tags=["Авторизация"])
def logout(value=Depends(identity), service=Depends(auth_service)):
    service.logout(value[1], value[0])
    return Response(status_code=204)


@router.get("/auth/me", response_model=UserOut, tags=["Авторизация"])
def me(user=Depends(current_user)):
    return user


@router.get("/events", response_model=EventPage, tags=["Мероприятия"])
def list_events(
    search: str = Query(default="", max_length=120),
    category: Category | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
    author_id: int | None = Query(default=None, ge=1),
    joined: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    value=Depends(optional_identity),
    db=Depends(get_db),
):
    def date(v):
        if v and v.tzinfo is None:
            raise AppError(400, "В фильтре даты укажите часовой пояс")
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v else None

    after, before = date(after), date(before)
    if after and before and after > before:
        raise AppError(400, "Некорректный диапазон дат")
    user = value[0] if value else None
    if joined and not user:
        raise AppError(401, "Войдите для просмотра своего участия")
    return EventService(db).list(
        user,
        search=search,
        category=category,
        after=after,
        before=before,
        author_id=author_id,
        joined_user=user.id if joined else None,
        page=page,
        page_size=page_size,
    )


@router.get("/events/{event_id}", response_model=EventOut, tags=["Мероприятия"])
def get_event(event_id: int, value=Depends(optional_identity), db=Depends(get_db)):
    service = EventService(db)
    return service.output(service.get(event_id), value[0] if value else None)


@router.post("/events", response_model=EventOut, status_code=201, tags=["Мероприятия"])
def create_event(data: EventInput, user=Depends(current_user), db=Depends(get_db)):
    return EventService(db).create(user, data)


@router.patch("/events/{event_id}", response_model=EventOut, tags=["Мероприятия"])
def update_event(event_id: int, data: EventPatch, user=Depends(current_user), db=Depends(get_db)):
    return EventService(db).update(event_id, user, data)


@router.delete("/events/{event_id}", status_code=204, tags=["Мероприятия"])
def delete_event(event_id: int, user=Depends(current_user), db=Depends(get_db)):
    EventService(db).delete(event_id, user)
    return Response(status_code=204)


@router.post("/events/{event_id}/join", response_model=EventOut, status_code=201, tags=["Участие"])
def join_event(event_id: int, user=Depends(current_user), db=Depends(get_db)):
    return EventService(db).join(event_id, user)


@router.delete("/events/{event_id}/join", status_code=204, tags=["Участие"])
def leave_event(event_id: int, user=Depends(current_user), db=Depends(get_db)):
    EventService(db).leave(event_id, user)
    return Response(status_code=204)


@router.get("/admin/users", response_model=list[UserOut], tags=["Администрирование"])
def users(page: int = Query(default=1, ge=1), user=Depends(admin), db=Depends(get_db)):
    return Users(db).list((page - 1) * 100)


@router.patch("/admin/users/{user_id}/role", response_model=UserOut, tags=["Администрирование"])
def role(user_id: int, data: RoleUpdate, actor=Depends(admin), db=Depends(get_db)):
    return UserService(db).set_role(actor, user_id, data.role)


@router.get("/admin/audit", tags=["Администрирование"])
def audit(limit: int = Query(default=100, ge=1, le=500), user=Depends(admin), db=Depends(get_db)):
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "action": row.action,
            "target": row.target,
            "created_at": row.created_at,
        }
        for row in UserService(db).audit(limit)
    ]
