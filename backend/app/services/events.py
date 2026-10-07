from datetime import timezone
from pydantic import ValidationError
from app.models import Event, Participation, utcnow
from app.repositories.store import Events, audit
from app.schemas import EventInput, EventOut
from app.core.errors import AppError


class EventService:
    def __init__(self, db):
        self.db, self.repo = db, Events(db)

    def get(self, event_id):
        event = self.repo.get(event_id)
        if not event:
            raise AppError(404, "Мероприятие не найдено")
        return event

    @staticmethod
    def can_edit(event, user):
        return bool(
            user
            and (
                user.role in {"moderator", "admin"}
                or (user.role == "organizer" and event.author_id == user.id)
            )
        )

    def output(self, event, user=None, joined_ids=None):
        joined = (
            event.id in joined_ids
            if joined_ids is not None
            else bool(user and self.repo.participation(event.id, user.id))
        )
        return EventOut(
            id=event.id,
            author_id=event.author_id,
            author_name=event.author.name,
            title=event.title,
            description=event.description,
            category=event.category,
            starts_at=event.starts_at.replace(tzinfo=timezone.utc),
            address=event.address,
            latitude=event.latitude,
            longitude=event.longitude,
            capacity=event.capacity,
            attendees=event.attendees,
            joined=joined,
            can_edit=self.can_edit(event, user),
        )

    def list(self, user, **filters):
        items, total = self.repo.page(**filters)
        joined_ids = self.repo.joined_ids(user.id) if user else set()
        return {
            "items": [self.output(item, user, joined_ids) for item in items],
            "total": total,
            "page": filters["page"],
            "page_size": filters["page_size"],
        }

    def create(self, user, data):
        if user.role not in {"organizer", "moderator", "admin"}:
            raise AppError(403, "Создавать события может организатор")
        if data.starts_at.replace(tzinfo=None) <= utcnow():
            raise AppError(400, "Дата события должна быть в будущем")
        values = data.model_dump()
        values["starts_at"] = data.starts_at.replace(tzinfo=None)
        event = Event(author_id=user.id, **values)
        self.db.add(event)
        self.db.flush()
        audit(self.db, user.id, "event.create", event.id)
        self.db.commit()
        return self.output(self.get(event.id), user)

    def update(self, event_id, user, changes):
        event = self.get(event_id)
        if not self.can_edit(event, user):
            raise AppError(403, "Нет прав на редактирование")
        merged = {key: getattr(event, key) for key in EventInput.model_fields}
        merged["starts_at"] = event.starts_at.replace(tzinfo=timezone.utc)
        merged.update(changes.model_dump(exclude_unset=True))
        try:
            data = EventInput.model_validate(merged)
        except ValidationError:
            raise AppError(400, "Некорректные данные мероприятия") from None
        if data.starts_at.replace(tzinfo=None) <= utcnow():
            raise AppError(400, "Дата события должна быть в будущем")
        if data.capacity < event.attendees:
            raise AppError(409, "Вместимость меньше числа участников")
        for key, value in data.model_dump().items():
            setattr(event, key, value.replace(tzinfo=None) if key == "starts_at" else value)
        audit(self.db, user.id, "event.update", event.id)
        self.db.commit()
        return self.output(event, user)

    def delete(self, event_id, user):
        event = self.get(event_id)
        if not self.can_edit(event, user):
            raise AppError(403, "Нет прав на удаление")
        audit(self.db, user.id, "event.delete", event.id)
        self.db.delete(event)
        self.db.commit()

    def join(self, event_id, user):
        event = self.get(event_id)
        if event.starts_at <= utcnow():
            raise AppError(400, "Мероприятие уже началось")
        if self.repo.participation(event_id, user.id):
            raise AppError(409, "Вы уже участвуете")
        if event.attendees >= event.capacity:
            raise AppError(409, "Свободных мест нет")
        event.attendees += 1
        self.db.add(Participation(event_id=event_id, user_id=user.id))
        audit(self.db, user.id, "participation.join", event.id)
        self.db.commit()
        return self.output(event, user)

    def leave(self, event_id, user):
        event = self.get(event_id)
        participation = self.repo.participation(event_id, user.id)
        if not participation:
            raise AppError(404, "Участие не найдено")
        event.attendees -= 1
        self.db.delete(participation)
        audit(self.db, user.id, "participation.leave", event.id)
        self.db.commit()
