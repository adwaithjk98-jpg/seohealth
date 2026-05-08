from collections.abc import Generator

from sqlalchemy import create_engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_dialect = make_url(settings.database_url).get_backend_name()

if _dialect == "sqlite":
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        future=True,
    )
elif _dialect == "postgresql":
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )
else:
    engine = create_engine(settings.database_url, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
