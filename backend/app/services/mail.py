"""SMTP delivery and an explicitly local mailbox for development."""

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from app.core.errors import AppError


class Mailer:
    def __init__(self, settings):
        self.settings = settings

    def send_code(self, email, challenge_id, code):
        s = self.settings
        if s.mail_backend == "file" and s.environment != "production":
            now = datetime.now(timezone.utc)
            path = s.mail_directory / f"{challenge_id}.json"
            try:
                s.mail_directory.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as mailbox:
                    json.dump(
                        {
                            "to": email,
                            "challenge_id": challenge_id,
                            "code": code,
                            "subject": "Сегодня идём — код входа",
                            "created_at": now.isoformat(),
                            "expires_at": (now + timedelta(minutes=10)).isoformat(),
                        },
                        mailbox,
                        ensure_ascii=False,
                    )
            except OSError:
                raise AppError(503, "Не удалось сохранить локальный код входа") from None
            return "development_file"
        if s.mail_backend != "smtp":
            raise AppError(503, "Почтовый сервис не настроен")
        message = EmailMessage()
        message["From"], message["To"] = s.smtp_sender, email
        message["Subject"] = "Сегодня идём — код входа"
        message.set_content(
            f"Ваш код входа: {code}. Срок действия: 10 минут. Никому не сообщайте код."
        )
        self._deliver(message)
        return "email"

    def send_test(self, email):
        """Explicit local setup test; this message never contains a login code."""
        if self.settings.mail_backend != "smtp":
            raise AppError(503, "Для тестового письма требуется SMTP")
        message = EmailMessage()
        message["From"], message["To"] = self.settings.smtp_sender, email
        message["Subject"] = "Сегодня идём — проверка почты"
        message.set_content("Настройки почты работают. Это тестовое письмо, а не код входа.")
        self._deliver(message)

    def _deliver(self, message):
        s = self.settings
        context = ssl.create_default_context()
        try:
            connection = (
                smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=10, context=context)
                if s.smtp_security == "ssl"
                else smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10)
            )
            with connection as smtp:
                if s.smtp_security == "starttls":
                    smtp.ehlo()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError:
            raise AppError(
                503, "SMTP отклонил вход. Проверьте адрес почты и пароль приложения в настройках"
            ) from None
        except smtplib.SMTPSenderRefused:
            raise AppError(503, "SMTP отклонил отправителя. Проверьте SMTP_SENDER") from None
        except smtplib.SMTPRecipientsRefused:
            raise AppError(503, "SMTP отклонил получателя. Проверьте адрес почты") from None
        except (ssl.SSLError, smtplib.SMTPNotSupportedError):
            raise AppError(
                503,
                "Не удалось установить защищённое соединение SMTP. Проверьте сервер, порт и TLS",
            ) from None
        except smtplib.SMTPException:
            raise AppError(503, "Почтовый сервер не принял письмо. Попробуйте позже") from None
        except OSError:
            raise AppError(
                503, "Нет соединения с SMTP. Проверьте интернет, сервер и порт в настройках"
            ) from None
