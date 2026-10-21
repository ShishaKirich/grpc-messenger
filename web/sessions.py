"""Серверные сеансы и устройства пользователя.

В подписанной cookie сеанса хранится случайный токен `sid`, в базе — только его хеш.
Благодаря этому сеанс можно завершить с сервера: кнопка «Выйти на всех устройствах»,
автоматический выход после смены пароля и т. д.

Устройство узнаём по отдельной долгоживущей cookie `device` (тоже случайный токен).
По ней работают «доверенные устройства» и письма о входе с нового устройства.
"""
import time

import aiosqlite
from fastapi import Request, Response

from auth_core.config import settings
from auth_core.db import fetch_all, fetch_one
from auth_core.security import new_token, token_hash

DEVICE_COOKIE = "device"
DEVICE_COOKIE_AGE = 400 * 24 * 3600  # максимум, который разрешают браузеры


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


# ---------- сеансы ----------

async def create_session(db: aiosqlite.Connection, request: Request, user_id: int) -> None:
    """Создаёт сеанс после успешного входа. Старое содержимое сессии стирается (защита от фиксации)."""
    now = int(time.time())
    sid = new_token()
    await db.execute(
        """INSERT INTO sessions (token_hash, user_id, ip, user_agent, created_at, last_seen_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (token_hash(sid), user_id, client_ip(request), user_agent(request), now, now,
         now + settings.session_lifetime_hours * 3600),
    )
    request.session.clear()
    request.session["sid"] = sid


async def current_user(db: aiosqlite.Connection, request: Request) -> tuple[aiosqlite.Row, int] | None:
    """Возвращает (пользователь, id сеанса) или None, если сеанс не действует."""
    sid = request.session.get("sid")
    if not sid:
        return None
    now = int(time.time())
    row = await fetch_one(db,
        """SELECT s.id AS session_id, s.last_seen_at, u.*
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND s.last_seen_at > ?""",
        (token_hash(sid), now, now - settings.session_idle_hours * 3600),
    )
    if row is None:
        request.session.pop("sid", None)
        return None
    if now - row["last_seen_at"] > 60:  # обновляем не чаще раза в минуту, чтобы не писать в базу на каждый запрос
        await db.execute("UPDATE sessions SET last_seen_at = ?, ip = ? WHERE id = ?",
                         (now, client_ip(request), row["session_id"]))
    return row, row["session_id"]


async def list_sessions(db: aiosqlite.Connection, user_id: int) -> list[aiosqlite.Row]:
    now = int(time.time())
    return await fetch_all(db,
        """SELECT id, ip, user_agent, created_at, last_seen_at FROM sessions
           WHERE user_id = ? AND expires_at > ? AND last_seen_at > ?
           ORDER BY last_seen_at DESC""",
        (user_id, now, now - settings.session_idle_hours * 3600),
    )


async def delete_session(db: aiosqlite.Connection, user_id: int, session_id: int) -> None:
    # user_id в условии обязателен: так нельзя завершить чужой сеанс, подставив его id
    await db.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))


async def delete_other_sessions(db: aiosqlite.Connection, user_id: int, keep_session_id: int | None) -> None:
    await db.execute("DELETE FROM sessions WHERE user_id = ? AND id IS NOT ?", (user_id, keep_session_id))


# ---------- устройства ----------

def device_token(request: Request) -> str | None:
    token = request.cookies.get(DEVICE_COOKIE)
    return token if token and len(token) <= 64 else None


def set_device_cookie(response: Response, token: str) -> None:
    response.set_cookie(DEVICE_COOKIE, token, max_age=DEVICE_COOKIE_AGE, httponly=True,
                        secure=settings.cookie_secure, samesite="lax")


async def is_trusted_device(db: aiosqlite.Connection, request: Request, user_id: int) -> bool:
    token = device_token(request)
    if not token:
        return False
    row = await fetch_one(db,
        "SELECT 1 FROM devices WHERE user_id = ? AND token_hash = ? AND trusted_until > ?",
        (user_id, token_hash(token), int(time.time())),
    )
    return row is not None


async def remember_device(db: aiosqlite.Connection, request: Request, response: Response,
                          user_id: int, trust: bool) -> bool:
    """Запоминает устройство при входе. Возвращает True, если устройство новое для пользователя."""
    now = int(time.time())
    token = device_token(request)
    if token is None:
        token = new_token()
        set_device_cookie(response, token)
    trusted_until = now + settings.trusted_device_days * 86400 if trust else None
    cur = await db.execute(
        """INSERT INTO devices (user_id, token_hash, ip, user_agent, first_seen_at, last_seen_at, trusted_until)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (user_id, token_hash) DO NOTHING""",
        (user_id, token_hash(token), client_ip(request), user_agent(request), now, now, trusted_until),
    )
    if cur.rowcount == 1:
        return True
    await db.execute(
        """UPDATE devices SET ip = ?, user_agent = ?, last_seen_at = ?,
               trusted_until = COALESCE(?, trusted_until)
           WHERE user_id = ? AND token_hash = ?""",
        (client_ip(request), user_agent(request), now, trusted_until, user_id, token_hash(token)),
    )
    return False


async def list_trusted_devices(db: aiosqlite.Connection, user_id: int) -> list[aiosqlite.Row]:
    return await fetch_all(db,
        """SELECT id, ip, user_agent, last_seen_at, trusted_until FROM devices
           WHERE user_id = ? AND trusted_until > ? ORDER BY last_seen_at DESC""",
        (user_id, int(time.time())),
    )


async def untrust_device(db: aiosqlite.Connection, user_id: int, device_id: int) -> None:
    await db.execute("UPDATE devices SET trusted_until = NULL WHERE id = ? AND user_id = ?", (device_id, user_id))


async def untrust_all_devices(db: aiosqlite.Connection, user_id: int) -> None:
    await db.execute("UPDATE devices SET trusted_until = NULL WHERE user_id = ?", (user_id,))


async def cleanup(db: aiosqlite.Connection) -> None:
    """Удаляет просроченные записи, чтобы таблицы не росли бесконечно."""
    now = int(time.time())
    await db.execute("DELETE FROM sessions WHERE expires_at < ? OR last_seen_at < ?",
                     (now, now - settings.session_idle_hours * 3600))
    await db.execute("DELETE FROM otp_codes WHERE expires_at < ?", (now - 86400,))
    await db.execute("DELETE FROM login_events WHERE created_at < ?", (now - 90 * 86400,))
    # Неподтверждённые регистрации старше суток удаляем, чтобы ими нельзя было «занять» чужие имена
    await db.execute("DELETE FROM users WHERE email_verified = 0 AND created_at < ?", (now - 86400,))
