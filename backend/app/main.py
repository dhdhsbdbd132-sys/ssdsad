import logging
import time
import uuid
import threading
from collections import defaultdict, deque
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from app.core.config import Settings
from app.core.db import Database
from app.services.mail import Mailer
from app.api.routes import router

log = logging.getLogger("todaygo")


def create_app(settings=None):
    settings = settings or Settings()
    app = FastAPI(
        title="Сегодня идём — API",
        version="1.0.0",
        description="Мероприятия Москвы, участие, OAuth2/OIDC и почтовая 2FA. Все данные клиентов передаются через API.",
    )
    app.state.settings, app.state.db, app.state.mailer = (
        settings,
        Database(settings.database_url),
        Mailer(settings),
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts.split(","))
    app.include_router(router)
    attempts = defaultdict(deque)
    lock = threading.Lock()

    @app.middleware("http")
    async def protection(request: Request, call_next):
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        length = request.headers.get("content-length")
        too_large = bool(length and (not length.isdigit() or int(length) > 65536))
        if not too_large:
            chunks, total = [], 0
            async for chunk in request.stream():
                total += len(chunk)
                if total > 65536:
                    too_large = True
                    break
                chunks.append(chunk)
            if not too_large:
                request._body = b"".join(chunks)
        if too_large:
            response = JSONResponse(
                {"error": "Слишком большой запрос", "request_id": request_id}, status_code=413
            )
        else:
            # Auth endpoints are limited per source address, never trust forwarded headers here.
            limited = False
            if request.url.path.startswith("/api/auth") and request.url.path != "/api/auth/me":
                ip = request.client.host if request.client else "unknown"
                now = time.monotonic()
                with lock:
                    # Bound memory and discard idle addresses.
                    if len(attempts) >= 10000:
                        for key in list(attempts):
                            if not attempts[key] or attempts[key][-1] < now - 60:
                                del attempts[key]
                    if ip not in attempts and len(attempts) >= 10000:
                        window = deque()
                        limited = True
                    else:
                        window = attempts[ip]
                    while window and window[0] < now - 60:
                        window.popleft()
                    limited = limited or len(window) >= settings.rate_limit
                    if not limited:
                        window.append(now)
                if limited:
                    response = JSONResponse(
                        {
                            "error": "Слишком много запросов. Подождите минуту",
                            "request_id": request_id,
                        },
                        status_code=429,
                        headers={"Retry-After": "60"},
                    )
            if not limited:
                try:
                    response = await call_next(request)
                except Exception:
                    # Do not log bodies, authorization headers, mail codes or database parameters.
                    log.error("Unhandled request error; request_id=%s", request_id)
                    response = JSONResponse(
                        {"error": "Внутренняя ошибка сервера", "request_id": request_id},
                        status_code=500,
                    )
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:",
            }
        )
        # FastAPI Swagger normally loads assets from CDN; allow only its documented hosts on /docs.
        if request.url.path in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; worker-src blob:"
            )
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {"error": str(exc.detail), "request_id": getattr(request.state, "request_id", None)},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            {
                "error": "Проверьте введённые данные",
                "details": details,
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=400,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(
            {"error": "Конфликт данных", "request_id": getattr(request.state, "request_id", None)},
            status_code=409,
        )

    @app.exception_handler(StaleDataError)
    async def concurrent_error(request, exc):
        return JSONResponse(
            {
                "error": "Данные изменились. Повторите действие",
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=409,
        )

    # All schema/input failures use the same documented HTTP 400 contract.
    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        for path in schema["paths"].values():
            for operation in path.values():
                if isinstance(operation, dict):
                    operation.get("responses", {}).pop("422", None)
        return schema

    app.openapi = openapi
    return app


app = create_app()
