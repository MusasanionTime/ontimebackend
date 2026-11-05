
import logging
import os
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.database.base import Base  # Keep model metadata registration compatible


logger = logging.getLogger(__name__)


def get_database_url() -> str | URL:
    """
    Load and normalize the database URL.

    Supports:
    - postgresql://
    - postgresql+psycopg://
    - postgresql+psycopg2://
    """

    database_url = (
        os.getenv("DATABASE_URL")
        or settings.DATABASE_URL
    )

    if not database_url or not database_url.strip():
        raise RuntimeError(
            "DATABASE_URL is missing. Configure it in Railway Variables."
        )

    database_url = database_url.strip()

    if "${{" in database_url or "}}" in database_url:
        raise RuntimeError(
            "DATABASE_URL contains an unresolved Railway variable reference. "
            "Check the DATABASE_URL reference in Railway Variables."
        )

    try:
        parsed_url = make_url(database_url)
    except Exception as exc:
        raise RuntimeError(
            "DATABASE_URL is invalid. Check the Railway PostgreSQL connection "
            "variable. Do not include quotation marks or placeholder values."
        ) from exc

    if parsed_url.drivername in ("postgres", "postgresql"):
        parsed_url = parsed_url.set(
            drivername="postgresql+psycopg"
        )

    if parsed_url.drivername not in (
        "postgresql+psycopg",
        "postgresql+psycopg2",
    ):
        raise RuntimeError(
            "Unsupported database driver. Expected PostgreSQL with psycopg "
            "or psycopg2."
        )

    if not parsed_url.host or not parsed_url.database:
        raise RuntimeError(
            "DATABASE_URL must include a PostgreSQL host and database name."
        )

    return parsed_url


DATABASE_URL = get_database_url()

# Never log the complete database URL because it contains credentials.
logger.info(
    "Database configuration loaded: driver=%s host=%s database=%s",
    DATABASE_URL.drivername,
    DATABASE_URL.host,
    DATABASE_URL.database,
)


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
    connect_args={
        "connect_timeout": 10,
    },
)


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> bool:
    """
    Verify that the application can connect to PostgreSQL.
    """

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        logger.info("Database connection successful.")
        return True

    except SQLAlchemyError:
        logger.exception("Database connection failed.")
        return False
