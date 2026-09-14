"""Configure Alembic for the versioned PostgreSQL application schema."""

from __future__ import annotations

from alembic import context

from app.db import (
    DATABASE_SCHEMA_NAME,
    Base,
    DatabaseSettings,
    create_database_engine,
)

config = context.config
target_metadata = Base.metadata


def _include_application_schema(
    name: str | None,
    type_: str,
    _parent_names: dict[str, str | None],
) -> bool:
    """Restrict reflected database objects to the explicit application schema."""
    return type_ != "schema" or name == DATABASE_SCHEMA_NAME


def run_migrations_offline() -> None:
    """Render deterministic PostgreSQL SQL without opening a connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=_include_application_schema,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the validated runtime database setting."""
    settings = DatabaseSettings.from_environment()
    engine = create_database_engine(settings)

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_schemas=True,
                include_name=_include_application_schema,
                compare_type=True,
                compare_server_default=True,
                transaction_per_migration=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
