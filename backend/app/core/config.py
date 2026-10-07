from pathlib import Path
from typing import Literal
from email.utils import parseaddr
from pydantic import EmailStr, Field, TypeAdapter, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )
    environment: str = "development"
    database_url: str = f"sqlite:///{ROOT}/.data/todaygo.db"
    secret_key: str = ""
    mail_backend: Literal["file", "smtp"] = "file"
    mail_directory: Path = ROOT / ".data/mail"
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl"] = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender: str = "TodayGo <noreply@example.com>"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    access_minutes: int = 15
    refresh_days: int = 7
    rate_limit: int = 20

    @model_validator(mode="after")
    def secure_settings(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unknown environment")
        if self.mail_backend == "smtp":
            if not self.smtp_host.strip() or any(c.isspace() for c in self.smtp_host):
                raise ValueError("SMTP_HOST must contain a server hostname")
            if self.smtp_port == 465 and self.smtp_security != "ssl":
                raise ValueError("SMTP port 465 requires SMTP_SECURITY=ssl")
            if self.smtp_port == 587 and self.smtp_security != "starttls":
                raise ValueError("SMTP port 587 requires SMTP_SECURITY=starttls")
            if bool(self.smtp_user) != bool(self.smtp_password):
                raise ValueError("SMTP_USER and SMTP_PASSWORD must be configured together")
            if "\r" in self.smtp_sender or "\n" in self.smtp_sender:
                raise ValueError("SMTP_SENDER must be a valid sender address")
            try:
                TypeAdapter(EmailStr).validate_python(parseaddr(self.smtp_sender)[1])
            except ValueError:
                raise ValueError("SMTP_SENDER must be a valid sender address") from None
        if len(self.secret_key) < 32:
            if self.environment == "production":
                raise ValueError("Production requires SECRET_KEY with at least 32 characters")
            import secrets

            path = ROOT / ".data/development.key"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                try:
                    with path.open("x") as f:
                        f.write(secrets.token_urlsafe(48))
                    path.chmod(0o600)
                except FileExistsError:
                    pass
            self.secret_key = path.read_text().strip()
        if self.environment == "production":
            if self.mail_backend != "smtp" or not self.smtp_host:
                raise ValueError("Production requires SMTP")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if "*" in self.allowed_hosts:
                raise ValueError("Production requires explicit ALLOWED_HOSTS")
        return self
