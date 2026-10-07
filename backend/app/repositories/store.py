from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, joinedload
from app.models import User, Event, Participation, RefreshSession, AuditLog


class Users:
    def __init__(self, db: Session):
        self.db = db

    def by_email(self, email):
        return self.db.scalar(select(User).where(User.email == email.lower()))

    def get(self, user_id):
        return self.db.get(User, user_id)

    def list(self, offset=0, limit=100):
        return self.db.scalars(select(User).order_by(User.id).offset(offset).limit(limit)).all()


class Events:
    def __init__(self, db: Session):
        self.db = db

    def get(self, event_id):
        return self.db.scalar(
            select(Event).options(joinedload(Event.author)).where(Event.id == event_id)
        )

    def page(self, search, category, after, before, author_id, joined_user, page, page_size):
        statement = select(Event).options(joinedload(Event.author))
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(
                or_(
                    Event.title.ilike(f"%{escaped}%", escape="\\"),
                    Event.description.ilike(f"%{escaped}%", escape="\\"),
                    Event.address.ilike(f"%{escaped}%", escape="\\"),
                )
            )
        if category:
            statement = statement.where(Event.category == category)
        if after:
            statement = statement.where(Event.starts_at >= after)
        if before:
            statement = statement.where(Event.starts_at <= before)
        if author_id:
            statement = statement.where(Event.author_id == author_id)
        if joined_user:
            statement = statement.where(
                Event.id.in_(
                    select(Participation.event_id).where(Participation.user_id == joined_user)
                )
            )
        total = self.db.scalar(select(func.count()).select_from(statement.subquery()))
        items = self.db.scalars(
            statement.order_by(Event.starts_at, Event.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return items, total

    def participation(self, event_id, user_id):
        return self.db.scalar(
            select(Participation).where(
                Participation.event_id == event_id, Participation.user_id == user_id
            )
        )

    def joined_ids(self, user_id):
        return set(
            self.db.scalars(select(Participation.event_id).where(Participation.user_id == user_id))
        )


class Sessions:
    def __init__(self, db: Session):
        self.db = db

    def by_hash(self, token_hash):
        return self.db.scalar(select(RefreshSession).where(RefreshSession.token_hash == token_hash))

    def family(self, family):
        return self.db.scalars(select(RefreshSession).where(RefreshSession.family == family)).all()

    def revoke(self, family):
        for row in self.family(family):
            row.revoked = True


def audit(db, actor_id, action, target):
    db.add(AuditLog(actor_id=actor_id, action=action, target=str(target)))
