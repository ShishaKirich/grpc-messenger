"""Журнал попыток входа: общий для сайта и мессенджера.

По нему же работает защита от подбора: 5 неудачных попыток за 15 минут —
и вход на этот email временно закрыт, откуда бы ни пришли попытки (сайт или клиент).
"""
import time

import aiosqlite

from .config import settings
from .db import fetch_one


async def recent_failures(db: aiosqlite.Connection, email: str) -> int:
    since = int(time.time()) - settings.login_window_seconds
    row = await fetch_one(db,
        "SELECT COUNT(*) AS n FROM login_events WHERE email = ? AND success = 0 AND created_at > ?",
        (email, since),
    )
    return row["n"]


async def log_login(db: aiosqlite.Connection, email: str, ip: str, user_agent: str,
                    success: bool, method: str) -> None:
    await db.execute(
        "INSERT INTO login_events (email, ip, user_agent, success, method, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (email, ip, user_agent, int(success), method, int(time.time())),
    )
