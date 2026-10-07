import argparse
import getpass
import secrets
from datetime import timedelta
from sqlalchemy import select
from app.core.config import Settings
from app.core.db import Database
from app.core.security import passwords
from app.models import User, Event, utcnow
from app.schemas import Register

SEED_EVENTS = [
    (
        "Джаз на крыше",
        "music",
        "Камерный концерт московского джазового квартета. Живой звук, закат и новые знакомства.",
        "Культурный центр ЗИЛ, ул. Восточная, 4",
        55.7064,
        37.6407,
        80,
    ),
    (
        "Прогулка по старой Москве",
        "culture",
        "Исследуем дворики Китай-города и узнаем истории улиц. Встречаемся у памятника Кириллу и Мефодию.",
        "Славянская площадь",
        55.7528,
        37.6331,
        25,
    ),
    (
        "Бегаем в Парке Горького",
        "sport",
        "Лёгкая пробежка пять километров в комфортном темпе. Подойдёт новичкам. После — кофе и разговоры.",
        "Парк Горького, главный вход",
        55.7298,
        37.6018,
        30,
    ),
    (
        "Пикник у Патриарших",
        "community",
        "Берите плед и любимые закуски: знакомимся, играем в настольные игры и проводим вечер вместе.",
        "Патриаршие пруды",
        55.7638,
        37.5927,
        20,
    ),
    (
        "Фотопрогулка по Зарядью",
        "education",
        "Практикуемся в городской фотографии. Разберём композицию и свет; подойдёт камера телефона.",
        "Парк Зарядье, парящий мост",
        55.7507,
        37.6283,
        15,
    ),
    (
        "Искусство на Винзаводе",
        "culture",
        "Посмотрим новые выставки современного искусства и обсудим работы за чашкой кофе.",
        "Винзавод, 4-й Сыромятнический пер., 1/8",
        55.7559,
        37.6652,
        18,
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed", "create-admin", "clean-auth"])
    parser.add_argument("--email")
    parser.add_argument("--name", default="Администратор")
    args = parser.parse_args()
    s = Settings()
    database = Database(s.database_url)
    with database.sessions() as db:
        if args.command == "seed":
            if s.environment == "production":
                raise SystemExit("Demo seed disabled in production")
            user = db.scalar(select(User).where(User.email == "moscow-demo@example.com"))
            if not user:
                user = User(
                    name="Команда «Сегодня идём»",
                    email="moscow-demo@example.com",
                    password_hash=passwords.hash(secrets.token_urlsafe(48)),
                    role="organizer",
                )
                db.add(user)
                db.flush()
            existing = set(db.scalars(select(Event.title).where(Event.author_id == user.id)))
            for index, (title, category, description, address, lat, lon, capacity) in enumerate(
                SEED_EVENTS
            ):
                if title not in existing:
                    db.add(
                        Event(
                            author_id=user.id,
                            title=title,
                            category=category,
                            description=description,
                            address=address,
                            latitude=lat,
                            longitude=lon,
                            capacity=capacity,
                            starts_at=(utcnow() + timedelta(days=index + 1)).replace(
                                hour=15, minute=0, second=0, microsecond=0
                            ),
                        )
                    )
            db.commit()
            print("Demo Moscow events ready (idempotent). No demo login credentials created.")
        elif args.command == "create-admin":
            if not args.email:
                raise SystemExit("--email required")
            data = Register(
                name=args.name, email=args.email, password=getpass.getpass("Password: ")
            )
            if db.scalar(select(User).where(User.email == str(data.email).lower())):
                raise SystemExit("User already exists")
            db.add(
                User(
                    name=data.name,
                    email=str(data.email).lower(),
                    password_hash=passwords.hash(data.password),
                    role="admin",
                )
            )
            db.commit()
            print("Admin created. Email 2FA is required on login.")
        else:
            from app.models import Challenge, RefreshSession, OAuthAttempt

            # Retain refresh rows until expiry for replay detection; then remove stale records.
            for model in (Challenge, RefreshSession, OAuthAttempt):
                for row in db.scalars(select(model).where(model.expires_at < utcnow())):
                    db.delete(row)
            db.commit()
            for path in s.mail_directory.glob("*.json"):
                import time

                if path.stat().st_mtime < time.time() - 600:
                    path.unlink()
            print("Expired authentication data removed")


if __name__ == "__main__":
    main()
