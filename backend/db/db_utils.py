import os
from contextlib import contextmanager

from dotenv import load_dotenv

load_dotenv(override=True, dotenv_path="backend/.env")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db import schemas

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    engine = create_engine(DATABASE_URL, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
else:
    engine = None
    SessionLocal = None


def init_db():
    """Create tables from ORM metadata. Raises if DATABASE_URL not set."""
    if engine is None:
        raise RuntimeError(
            "DATABASE_URL not set. Set it to a valid SQLAlchemy URL to initialize the DB."
        )
    schemas.Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    """Yield a SQLAlchemy session and handle commit/rollback/close.

    Usage:
        with get_session() as session:
            session.add(obj)
            ...
    """
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL not set. Cannot create session.")
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except:
        s.rollback()
        raise
    finally:
        s.close()
