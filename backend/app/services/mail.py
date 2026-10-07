import json
import os
import smtplib
from email.message import EmailMessage
from app.core.errors import AppError


class Mailer:
    def __init__(self, settings):
        self.settings = settings

    def send_code(self, email, challenge_id, code):
        s = self.settings
        if s.mail_backend == "file" and s.environment != "production":
            s.mail_directory.mkdir(parents=True, exist_ok=True)
            path = s.mail_directory / f"{challenge_id}.json"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(
                    {"to": email, "code": code, "subject": "Сегодня идём — код входа"},
                    f,
                    ensure_ascii=False,
                )
            return
        if s.mail_backend != "smtp":
            raise AppError(503, "Почтовый сервис не настроен")
        message = EmailMessage()
        message["From"], message["To"] = s.smtp_sender, email
        message["Subject"] = "Сегодня идём — код входа"
        message.set_content(
            f"Ваш код входа: {code}. Срок действия: 10 минут. Никому не сообщайте код."
        )
        try:
            import ssl

            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            raise AppError(503, "Не удалось отправить письмо. Попробуйте позже") from None
