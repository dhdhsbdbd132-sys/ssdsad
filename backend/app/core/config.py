from pathlib import Path
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )
    environment: str = "development"
    database_url: str = f"sqlite:///{ROOT}/.data/todaygo.db"
    secret_key: str = ""
    mail_backend: str = "file"
    mail_directory: Path = ROOT / ".data/mail"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_sender: str = "TodayGo <noreply@example.com>"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_issuer: str = "https://accounts.google.com"
    oauth_discovery_url: str = "https://accounts.google.com/.well-known/openid-configuration"
    oauth_redirect_uri: str = "http://localhost:8000/api/auth/oauth/callback"
    access_minutes: int = 15
    refresh_days: int = 7
    rate_limit: int = 20

    @model_validator(mode="after")
    def secure_settings(self):
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("Unknown environment")
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
            if not self.oauth_redirect_uri.startswith("https://"):
                raise ValueError("Production OAuth callback requires HTTPS")
            if "*" in self.allowed_hosts:
                raise ValueError("Production requires explicit ALLOWED_HOSTS")
        return self
