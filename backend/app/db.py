from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings


def make_engine(settings: Settings) -> Engine:
    """SQLite engine with explicit transactions, foreign keys and WAL.

    ``autocommit=False`` (Python 3.12) makes every statement, including a plain SELECT, run
    inside a transaction, so a request sees one consistent snapshot. Foreign-key and journal
    pragmas only take effect outside a transaction, hence the brief autocommit window.
    """
    settings.ensure_dirs()
    engine = create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"autocommit": False, "timeout": settings.sqlite_timeout_seconds},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, _record) -> None:  # noqa: ANN001
        dbapi_connection.autocommit = True
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.autocommit = False

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, autoflush=False)


def get_session(request: Request) -> Iterator[Session]:
    """One Session per request; services decide when to commit."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
