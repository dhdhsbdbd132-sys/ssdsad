from alembic import context
from app.core.config import Settings
from app.core.db import Database, Base
from app import models  # noqa: F401 -- register ORM tables


def run():
    settings = Settings()
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url, target_metadata=Base.metadata, literal_binds=True
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        db = Database(settings.database_url)
        with db.engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()


run()
