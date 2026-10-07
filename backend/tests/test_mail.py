import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import smtplib
import ssl
from unittest.mock import MagicMock

import pytest
from dotenv import dotenv_values
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.models import Challenge, User, utcnow
from app.services.mail import Mailer


def smtp_settings(**overrides):
    values = {
        "_env_file": None,
        "environment": "test",
        "secret_key": "test-key-" * 8,
        "mail_backend": "smtp",
        "smtp_host": "smtp.mail.ru",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "smtp_user": "sender@mail.ru",
        "smtp_password": "private-application-password",
        "smtp_sender": "Сегодня идём <sender@mail.ru>",
    }
    return Settings(**{**values, **overrides})


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mailru_uses_implicit_ssl_with_certificate_verification(monkeypatch):
    transport, plain = MagicMock(), MagicMock()
    monkeypatch.setattr(smtplib, "SMTP_SSL", transport)
    monkeypatch.setattr(smtplib, "SMTP", plain)
    smtp = transport.return_value.__enter__.return_value
    assert (
        Mailer(smtp_settings()).send_code("recipient@example.com", "challenge", "004201") == "email"
    )
    plain.assert_not_called()
    args, kwargs = transport.call_args
    assert args == ("smtp.mail.ru", 465)
    assert kwargs["context"].check_hostname
    assert kwargs["context"].verify_mode == ssl.CERT_REQUIRED
    smtp.starttls.assert_not_called()
    smtp.login.assert_called_once_with("sender@mail.ru", "private-application-password")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "recipient@example.com"
    assert "004201" in message.get_content()


def test_starttls_finishes_tls_before_authentication(monkeypatch):
    transport, implicit = MagicMock(), MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", transport)
    monkeypatch.setattr(smtplib, "SMTP_SSL", implicit)
    smtp = transport.return_value.__enter__.return_value
    Mailer(smtp_settings(smtp_port=587, smtp_security="starttls")).send_code(
        "recipient@example.com", "challenge", "004201"
    )
    implicit.assert_not_called()
    assert [call[0] for call in smtp.method_calls] == [
        "ehlo",
        "starttls",
        "ehlo",
        "login",
        "send_message",
    ]
    context = smtp.starttls.call_args.kwargs["context"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            smtplib.SMTPAuthenticationError(535, b"private-application-password"),
            "пароль приложения",
        ),
        (
            smtplib.SMTPSenderRefused(550, b"private-application-password", "sender@mail.ru"),
            "отправителя",
        ),
        (smtplib.SMTPRecipientsRefused({"recipient@example.com": (550, b"secret")}), "получателя"),
        (ssl.SSLError("private-application-password"), "защищённое соединение"),
        (OSError("private-application-password"), "Нет соединения"),
    ],
)
def test_smtp_failure_is_actionable_and_does_not_expose_credentials(monkeypatch, failure, expected):
    def broken(*args, **kwargs):
        raise failure

    monkeypatch.setattr(smtplib, "SMTP_SSL", broken)
    with pytest.raises(AppError) as error:
        Mailer(smtp_settings()).send_code("recipient@example.com", "challenge", "004201")
    assert error.value.status_code == 503
    assert expected in error.value.detail
    assert "private-application-password" not in error.value.detail
    assert "004201" not in error.value.detail


@pytest.mark.parametrize(
    "overrides",
    [
        {"mail_backend": "unknown"},
        {"smtp_port": 0},
        {"smtp_port": 65536},
        {"smtp_security": "plain"},
        {"smtp_security": "starttls", "smtp_port": 465},
        {"smtp_security": "ssl", "smtp_port": 587},
        {"smtp_host": ""},
        {"smtp_password": ""},
        {"smtp_sender": "not-an-email"},
    ],
)
def test_invalid_mail_configuration_is_rejected(overrides):
    with pytest.raises(ValueError):
        smtp_settings(**overrides)


def test_local_mail_is_marked_honestly_and_written_utf8(app, client):
    result = client.post(
        "/api/auth/register",
        json={
            "name": "Мария",
            "email": "maria@example.com",
            "password": "PasswordTest42",
            "role": "attendee",
        },
    )
    assert result.status_code == 201
    assert result.json()["delivery"] == "development_file"
    assert "code" not in result.json()
    cid = result.json()["challenge_id"]
    data = json.loads(
        (app.state.settings.mail_directory / f"{cid}.json").read_text(encoding="utf-8")
    )
    assert data["subject"] == "Сегодня идём — код входа" and data["challenge_id"] == cid
    issued, expires = (
        datetime.fromisoformat(data[field]) for field in ("created_at", "expires_at")
    )
    assert expires - issued == timedelta(minutes=10)


def test_registration_failure_rolls_back_user_and_challenge(client, app, monkeypatch):
    app.state.mailer = Mailer(smtp_settings())

    def broken(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"private-application-password")

    monkeypatch.setattr(smtplib, "SMTP_SSL", broken)
    data = {
        "name": "Мария",
        "email": "maria@example.com",
        "password": "PasswordTest42",
        "role": "attendee",
    }
    result = client.post("/api/auth/register", json=data)
    assert result.status_code == 503 and "private-application-password" not in result.text
    with app.state.db.sessions() as db:
        assert db.scalar(select(User).where(User.email == data["email"])) is None
        assert db.scalar(select(Challenge)) is None
    # A failed email attempt must not leave the address taken.
    app.state.mailer = Mailer(app.state.settings)
    assert client.post("/api/auth/register", json=data).status_code == 201


def test_failed_new_email_keeps_previous_challenge_valid(client, app, account, monkeypatch):
    account()
    login = {"email": "organizer@example.com", "password": "StrongPassword42"}
    previous = client.post("/api/auth/login", json=login).json()["challenge_id"]
    code = json.loads(
        (app.state.settings.mail_directory / f"{previous}.json").read_text(encoding="utf-8")
    )["code"]
    app.state.mailer = Mailer(smtp_settings())

    def broken(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP_SSL", broken)
    assert client.post("/api/auth/login", json=login).status_code == 503
    assert (
        client.post("/api/auth/verify", json={"challenge_id": previous, "code": code}).status_code
        == 200
    )


def test_smtp_test_message_has_no_login_code(monkeypatch):
    transport = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP_SSL", transport)
    Mailer(smtp_settings()).send_test("recipient@example.com")
    message = transport.return_value.__enter__.return_value.send_message.call_args.args[0]
    assert "проверка почты" in message["Subject"]
    assert "не код входа" in message.get_content()


def test_email_setup_preserves_database_secret_and_comments(tmp_path):
    setup = load_script("configure_email")
    path = tmp_path / ".env"
    original = '# Моя база\nDATABASE_URL="sqlite:///saved.db"\nSECRET_KEY="keep-this-exact"\nMAIL_BACKEND=file\nSMTP_PASSWORD=old\n'
    path.write_text(original, encoding="utf-8")
    password = 'app "quoted" \\ password # café'
    setup.save_settings(path, {"MAIL_BACKEND": "smtp", "SMTP_PASSWORD": password})
    values = dotenv_values(path, interpolate=False)
    assert values["SMTP_PASSWORD"] == password and values["MAIL_BACKEND"] == "smtp"
    assert (
        values["DATABASE_URL"] == "sqlite:///saved.db" and values["SECRET_KEY"] == "keep-this-exact"
    )
    assert path.read_text(encoding="utf-8").startswith("# Моя база\n")
    backups = list((tmp_path / ".data/email-settings-backups").glob("*.bak"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == original


def test_failed_atomic_email_save_preserves_old_env(tmp_path, monkeypatch):
    setup = load_script("configure_email")
    path = tmp_path / ".env"
    path.write_text("SECRET_KEY=keep\nMAIL_BACKEND=file\n", encoding="utf-8")
    original = path.read_bytes()

    def broken(*args, **kwargs):
        raise OSError("disk error")

    monkeypatch.setattr(setup.os, "replace", broken)
    with pytest.raises(OSError):
        setup.save_settings(path, {"MAIL_BACKEND": "smtp"})
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".env.todaygo-*"))


def test_local_reader_excludes_used_and_expired_codes(client, app, account):
    reader = load_script("read_dev_mail")
    account()
    assert reader.valid_local_code(app.state.settings, "organizer@example.com") is None
    result = client.post(
        "/api/auth/login", json={"email": "organizer@example.com", "password": "StrongPassword42"}
    )
    cid = result.json()["challenge_id"]
    found = reader.valid_local_code(app.state.settings, "ORGANIZER@example.com")
    assert found and found[1] > datetime.now(timezone.utc)
    with app.state.db.sessions() as db:
        db.get(Challenge, cid).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert reader.valid_local_code(app.state.settings, "organizer@example.com") is None


def test_local_reader_rejects_smtp():
    with pytest.raises(ValueError):
        load_script("read_dev_mail").valid_local_code(smtp_settings(), "organizer@example.com")


def test_mailru_setup_default_saves_credentials_without_sending(tmp_path, monkeypatch, capsys):
    setup = load_script("configure_email")
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    path = tmp_path / ".env"
    path.write_text(
        f'SECRET_KEY="{"s" * 64}"\nDATABASE_URL="sqlite:///preserved.db"\n', encoding="utf-8"
    )
    answers = iter(["", "sender@mail.ru", ""])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: "private-application-password")
    transport = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP_SSL", transport)
    assert setup.main() == 0
    transport.assert_not_called()
    loaded = Settings(_env_file=path)
    assert loaded.smtp_host == "smtp.mail.ru" and loaded.smtp_port == 465
    assert loaded.smtp_security == "ssl" and loaded.mail_backend == "smtp"
    assert loaded.smtp_user == "sender@mail.ru"
    assert loaded.smtp_password == "private-application-password"
    assert loaded.database_url == "sqlite:///preserved.db"
    assert "private-application-password" not in capsys.readouterr().out


def test_failed_setup_test_does_not_save_credentials(tmp_path, monkeypatch, capsys):
    setup = load_script("configure_email")
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    path = tmp_path / ".env"
    original = f'SECRET_KEY="{"s" * 64}"\nMAIL_BACKEND=file\n'
    path.write_text(original, encoding="utf-8")
    answers = iter(["", "sender@mail.ru", "да"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(setup.getpass, "getpass", lambda prompt: "private-application-password")

    def broken(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"private-application-password")

    monkeypatch.setattr(smtplib, "SMTP_SSL", broken)
    assert setup.main() == 1
    assert path.read_text(encoding="utf-8") == original
    assert "private-application-password" not in capsys.readouterr().out
