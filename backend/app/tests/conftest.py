import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import *  # noqa: F401,F403  ensure all models are registered


def _alembic_config(db_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture(scope="session")
def test_db_url() -> str:
    settings = get_settings()
    url = settings.test_database_url or settings.database_url
    assert "test" in url, (
        "Refusing to run tests against a database whose URL doesn't look like a "
        "test database — set TEST_DATABASE_URL explicitly."
    )
    return url


@pytest.fixture(scope="session")
def _migrated_engine(test_db_url):
    engine = create_engine(test_db_url, future=True)

    # Real Postgres, real migrations — never SQLite, never Base.metadata.create_all
    # for tests, so the same migration path used in production is exercised here.
    cfg = _alembic_config(test_db_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(_migrated_engine) -> Session:
    connection = _migrated_engine.connect()
    transaction = connection.begin()
    # Service code calls session.commit(); join_transaction_mode="create_savepoint"
    # translates those into SAVEPOINT release/rollback instead of ending the outer
    # transaction, so the whole test still rolls back cleanly on close.
    SessionFactory = sessionmaker(bind=connection, future=True, join_transaction_mode="create_savepoint")
    session = SessionFactory()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
