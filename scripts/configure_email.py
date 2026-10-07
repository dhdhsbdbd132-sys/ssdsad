"""Interactive local SMTP setup. Credentials stay in the ignored project .env."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PRESETS = {
    "1": ("Mail.ru", "smtp.mail.ru", 465, "ssl"),
    "2": ("Яндекс", "smtp.yandex.ru", 465, "ssl"),
    "3": ("Gmail", "smtp.gmail.com", 465, "ssl"),
}


def update_env_text(source: str, values: dict[str, str]) -> str:
    """Keep every unrelated line, including database and application secrets."""
    remaining = dict(values)
    lines = []
    for line in source.splitlines(keepends=True):
        match = re.match(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_]\w*)[ \t]*=", line)
        key = match.group(1) if match else None
        if key in values:
            if key in remaining:
                lines.append(f"{key}={json.dumps(remaining.pop(key), ensure_ascii=False)}\n")
        else:
            lines.append(line)
    result = "".join(lines)
    if result and not result.endswith("\n"):
        result += "\n"
    result += "".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in remaining.items()
    )
    return result


def save_settings(path: Path, values: dict[str, str]) -> None:
    """Atomically replace .env, with a private backup of its previous contents."""
    original = path.read_bytes() if path.exists() else None
    source = original.decode("utf-8-sig") if original is not None else ""
    updated = update_env_text(source, values).encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".env.todaygo-", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        if original is not None:
            if path.read_bytes() != original:
                raise RuntimeError(
                    "Файл .env изменился во время настройки. Запустите мастер ещё раз"
                )
            backups = path.parent / ".data" / "email-settings-backups"
            backups.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix="env-before-smtp-", suffix=".bak", dir=backups, delete=False
            ) as backup:
                os.chmod(backup.name, 0o600)
                backup.write(original)
        elif path.exists():
            raise RuntimeError("Файл .env появился во время настройки. Запустите мастер ещё раз")
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, 0o600)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ask(text: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(text + suffix + ": ").strip()
    return value or default


def main() -> int:
    from pydantic import EmailStr, TypeAdapter, ValidationError
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.services.mail import Mailer

    print("Сегодня идём — настройка реальной почты")
    print("Закройте приложение перед настройкой. После сохранения запустите его заново.")
    print(
        "В тестовом режиме коды сохраняются локально, письма не отправляются. Здесь настраивается SMTP."
    )
    print("1 — Mail.ru (рекомендуется), 2 — Яндекс, 3 — Gmail, 4 — другой SMTP")
    provider = ask("Почтовый сервис", "1")
    if provider in PRESETS:
        name, host, port, security = PRESETS[provider]
        print(f"{name}: {host}, порт {port}, SSL с проверкой сертификата.")
    elif provider == "4":
        host = ask("Адрес SMTP-сервера")
        security = ask("Защита: ssl (465) или starttls (587)", "ssl").lower()
        port = int(ask("Порт", "465" if security == "ssl" else "587"))
    else:
        print("Выберите номер 1, 2, 3 или 4. Настройки не изменены.")
        return 1
    username = str(TypeAdapter(EmailStr).validate_python(ask("Полный адрес почты отправителя")))
    if provider == "1":
        print(
            "Mail.ru: Настройки → Все настройки → Безопасность → Пароли для внешних приложений → Создать."
        )
        print("Используйте этот пароль приложения. Обычный пароль аккаунта может быть отклонён.")
    else:
        print("Используйте пароль приложения, разрешённый вашим почтовым сервисом для SMTP.")
    password = getpass.getpass("Пароль приложения (ввод скрыт): ")
    if not password or any(c in password for c in "\r\n\x00") or "${" in password:
        print(
            "Требуется непустой пароль приложения без управляющих символов. Настройки не изменены."
        )
        return 1
    values = {
        "MAIL_BACKEND": "smtp",
        "SMTP_HOST": host,
        "SMTP_PORT": str(port),
        "SMTP_SECURITY": security,
        "SMTP_USER": username,
        "SMTP_PASSWORD": password,
        "SMTP_SENDER": f"Сегодня идём <{username}>",
    }
    try:
        settings = Settings(
            _env_file=ROOT / ".env",
            mail_backend="smtp",
            smtp_host=host,
            smtp_port=port,
            smtp_security=security,
            smtp_user=username,
            smtp_password=password,
            smtp_sender=values["SMTP_SENDER"],
        )
    except ValidationError:
        print(
            "Настройки SMTP некорректны. Проверьте сервер, порт и SSL/STARTTLS. Файл .env не изменён."
        )
        return 1
    # Explicit local choice: no connection or real message is sent before this prompt.
    if ask(f"Отправить тестовое письмо на {username}? (д/Н)", "н").lower() in {
        "д",
        "да",
        "y",
        "yes",
    }:
        try:
            Mailer(settings).send_test(username)
        except AppError as error:
            print(error.detail)
            print(
                "Тест не прошёл, предыдущие настройки сохранены. Проверьте данные и повторите мастер."
            )
            return 1
        print("SMTP принял тестовое письмо. Проверьте Входящие и Спам.")
    save_settings(ROOT / ".env", values)
    print(
        "Готово. Данные SMTP сохранены только в локальном .env; база и секрет приложения сохранены."
    )
    print("Запустите START_WINDOWS.bat заново, затем запросите новый код входа.")
    print(
        "Письма будут отправляться через ваш SMTP. Получение также зависит от почтового сервиса и Спама."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nНастройка отменена. Файл .env не изменён.")
        raise SystemExit(1) from None
    except Exception:
        # Never print exception reprs: SMTP libraries and validation can contain credentials.
        print("Не удалось завершить настройку. Проверьте адрес, порт и доступ к файлу .env.")
        raise SystemExit(1) from None
