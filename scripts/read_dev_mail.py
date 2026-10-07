"""Explicit local development tool. Never runs in SMTP/production mode."""

import hmac
import json
import sys
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def valid_local_code(settings, email):
    """Return only a code that the current database will actually accept."""
    from app.core.db import Database
    from app.core.security import code_digest
    from app.models import Challenge, User, utcnow

    if settings.environment == "production" or settings.mail_backend != "file":
        raise ValueError(
            "Локальная почта доступна только в тестовом режиме. SMTP-коды приходят на почту."
        )
    files = sorted(
        settings.mail_directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    database = Database(settings.database_url)
    try:
        with database.sessions() as db:
            for path in files:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        continue
                    if data.get("to", "").lower() != email.lower():
                        continue
                    cid, code = data.get("challenge_id", path.stem), data["code"]
                    if not isinstance(cid, str) or not isinstance(code, str):
                        continue
                    row = db.get(Challenge, cid)
                    if not row or row.used or row.attempts >= 5 or row.expires_at <= utcnow():
                        continue
                    user = db.get(User, row.user_id)
                    if not user or not user.active or user.email.lower() != email.lower():
                        continue
                    if not hmac.compare_digest(
                        row.code_hash, code_digest(settings.secret_key, cid, code)
                    ):
                        continue
                    return code, row.expires_at.replace(tzinfo=timezone.utc)
                except (ValueError, KeyError, TypeError):
                    continue
    finally:
        database.engine.dispose()
    return None


def main():
    from app.core.config import Settings

    settings = Settings()
    if settings.environment == "production" or settings.mail_backend != "file":
        print(
            "Включена реальная почта. Ищите код во Входящих или Спаме; локальные коды недоступны."
        )
        return 1
    print("Локальная тестовая почта. Письмо не отправлялось на ваш email.")
    email = input("Почта, указанная при регистрации: ").strip().lower()
    result = valid_local_code(settings, email)
    if result is None:
        print("Действующего кода нет. Зарегистрируйтесь или запросите новый вход в приложении.")
        return 1
    code, expires_at = result
    print("Код:", code, "(только для локального тестирования)")
    print("Действует до", expires_at.astimezone().strftime("%H:%M:%S %d.%m.%Y"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit(1) from None
    except Exception:
        print("Не удалось прочитать локальную почту. Сначала запустите START_WINDOWS.bat.")
        raise SystemExit(1) from None
