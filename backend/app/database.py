from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False} if _sqlite else {})

if _sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_rules(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")  # SQLite ignores foreign keys unless asked

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns() -> list[str]:
    """Add columns that newer versions of the app need to an existing SQLite database.
    (New tables are created by create_all; SQLite cannot add columns that way.)"""
    if not _sqlite:
        return []
    from sqlalchemy import inspect, text
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                kind = col.type.compile(dialect=engine.dialect)
                sql = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {kind}'
                if default is not None:
                    sql += " DEFAULT " + (f"'{default}'" if isinstance(default, str) else str(int(default)))
                conn.execute(text(sql))
                added.append(f"{table.name}.{col.name}")
    return added
