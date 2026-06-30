import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all models so Alembic can detect them
from app.core.database import Base  # noqa: F401
import app.modules.user_management.models  # noqa: F401
import app.modules.document_storage.models  # noqa: F401
import app.modules.ocr_processing.models  # noqa: F401
import app.modules.document_classification.models  # noqa: F401
import app.modules.email_integration.models  # noqa: F401
import app.modules.shipment_identification.models  # noqa: F401
import app.models.activity_log  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow DATABASE_URL_SYNC env var to override alembic.ini (used in production/Docker)
_db_url = os.environ.get("DATABASE_URL_SYNC")
if _db_url:
    config.set_main_option("sqlalchemy.url", _db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
