from typing import Generator
from sqlmodel import SQLModel, Session, create_engine

from app.config import settings

# SQLite requires check_same_thread=False so FastAPI can use the connection across requests
connect_args = (
    {"check_same_thread": False}
    if settings.DATABASE_URL.startswith("sqlite")
    else {}
)

# Create the database engine
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)


def create_db_and_tables() -> None:
    """Create all database tables defined by SQLModel models."""
    # Ensure all models are imported before creating tables
    import app.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Provide a database session to route handlers and close it afterwards."""
    with Session(engine) as session:
        yield session
