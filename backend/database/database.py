import logging
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "portfolio.db"


def _is_db_healthy(path: Path) -> bool:
    """Проверяет целостность файла SQLite через PRAGMA integrity_check."""
    if not path.exists():
        return True  # файла нет — создавать нечего, всё в порядке
    try:
        con = sqlite3.connect(str(path))
        try:
            result = con.execute("PRAGMA integrity_check").fetchone()
            return result is not None and result[0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False


def _make_engine(path: Path):
    return create_engine(f"sqlite:///{path}", echo=False)


def _ensure_healthy_db() -> Path:
    """Если БД повреждена ('database disk image is malformed'), сохраняет
    копию битого файла и пересоздаёт чистую базу, чтобы приложение запускалось."""
    if _is_db_healthy(DB_PATH):
        return DB_PATH

    backup_path = DB_PATH.with_name(f"portfolio.corrupted.{int(__import__('time').time())}.db.bak")
    logger.warning(
        "База данных %s повреждена (database disk image is malformed). "
        "Сохраняем копию как %s и создаём новую чистую БД.",
        DB_PATH, backup_path,
    )
    try:
        DB_PATH.replace(backup_path)
    except OSError as exc:
        logger.error("Не удалось переименовать повреждённую БД: %s. Удаляем файл.", exc)
        DB_PATH.unlink(missing_ok=True)

    # Создаём пустой файл — таблицы будут созданы Base.metadata.create_all
    DB_PATH.touch()
    return DB_PATH


DB_PATH = _ensure_healthy_db()
engine = _make_engine(DB_PATH)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    # WAL вместо journal=delete: устойчивее к обрывам записи (краш процесса,
    # антивирус, синхронизация облака), читающие запросы не блокируются пишущими
    cursor.execute("PRAGMA journal_mode=WAL")
    # Если всё же база повреждена — падать сразу на первом запросе, а не молча
    cursor.execute("PRAGMA quick_check")
    row = cursor.fetchone()
    if row is None or row[0] != "ok":
        cursor.close()
        raise sqlite3.DatabaseError(
            f"SQLite database at {DB_PATH} failed quick_check: {row}"
        )
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()