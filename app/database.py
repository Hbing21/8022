from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import get_settings

settings = get_settings()

if settings.database_url.startswith("sqlite"):
    connect_args = {
        "check_same_thread": False,
        # SQLite 锁等待：降低 “database is locked” 概率
        "timeout": 15,
    }
else:
    connect_args = {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        del connection_record
        cursor = dbapi_connection.cursor()
        # WAL 对并发读写更友好；busy_timeout 提供锁等待窗口
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=15000;")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
