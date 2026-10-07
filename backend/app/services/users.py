from sqlalchemy import select
from app.models import RefreshSession
from app.repositories.store import Users, audit
from app.core.errors import AppError


class UserService:
    def __init__(self, db):
        self.db, self.repo = db, Users(db)

    def set_role(self, actor, user_id, role):
        user = self.repo.get(user_id)
        if not user:
            raise AppError(404, "Пользователь не найден")
        if actor.id == user.id:
            raise AppError(400, "Нельзя изменять собственную роль")
        user.role = role
        for row in self.db.scalars(select(RefreshSession).where(RefreshSession.user_id == user.id)):
            row.revoked = True
        audit(self.db, actor.id, "user.role." + role, user.id)
        self.db.commit()
        return user

    def audit(self, limit):
        from app.models import AuditLog

        return self.db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
