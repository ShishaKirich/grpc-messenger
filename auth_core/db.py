"""Работа с базой данных SQLite (асинхронно, через aiosqlite).

Каждый запрос получает своё соединение. Режим WAL позволяет нескольким
процессам и потокам читать базу одновременно, пока кто-то пишет.
"""
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .config import settings

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# Колонки, добавленные после первой версии. CREATE TABLE IF NOT EXISTS не меняет уже
# существующие таблицы, поэтому в старую базу их нужно добавить через ALTER TABLE.
MIGRATIONS = {
    "users": {
        "password_changed_at": "INTEGER",  # nosec B105 — тип колонки, а не пароль
        "totp_secret": "TEXT",  # nosec B105
        "totp_enabled": "INTEGER NOT NULL DEFAULT 0",
        "totp_last_step": "INTEGER",
    },
}


async def connect() -> aiosqlite.Connection:
    # isolation_level=None — режим автокоммита: каждый INSERT/UPDATE сразу фиксируется.
    # Блокировка на запись держится микросекунды, и параллельные запросы не мешают друг другу.
    conn = await aiosqlite.connect(settings.database_path, timeout=10, isolation_level=None)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA busy_timeout = 10000")  # ждать до 10 с, если база занята записью
    return conn


async def init_db(extra_schema: Path | None = None) -> None:
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = await connect()
    try:
        await conn.execute("PRAGMA journal_mode = WAL")
        for table, columns in MIGRATIONS.items():
            existing = {row["name"] for row in await conn.execute_fetchall(f"PRAGMA table_info({table})")}  # nosec B608 — имена из константы
            if existing:  # таблица уже есть — добавляем недостающие колонки
                for name, ddl in columns.items():
                    if name not in existing:
                        try:
                            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")  # nosec B608
                        except aiosqlite.OperationalError:
                            pass  # колонку только что добавил соседний процесс
        await conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        if extra_schema:  # таблицы мессенджера создаёт gRPC-сервер
            await conn.executescript(extra_schema.read_text(encoding="utf-8"))
    finally:
        await conn.close()


@asynccontextmanager
async def opened():
    """`async with opened() as db:` — соединение на время одного запроса (для gRPC-сервера)."""
    conn = await connect()
    try:
        yield conn
    finally:
        await conn.close()


async def get_db():
    """Зависимость FastAPI: открывает соединение на время запроса и закрывает после."""
    conn = await connect()
    try:
        yield conn
    finally:
        await conn.close()


# Короткие помощники для SELECT: сразу читают результат и закрывают курсор.
async def fetch_one(conn: aiosqlite.Connection, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
    rows = await conn.execute_fetchall(sql, params)
    return rows[0] if rows else None


async def fetch_all(conn: aiosqlite.Connection, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
    return list(await conn.execute_fetchall(sql, params))
