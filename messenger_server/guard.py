"""Проверка токена сеанса для каждого вызова gRPC.

Пользователь определяется ТОЛЬКО по токену из метаданных `authorization: Bearer <токен>`.
Поля вроде `sender` в запросах сервер игнорирует и заполняет сам: в старой версии
мессенджера личность бралась из заголовка `username`, и выдать себя за другого было можно.

Таблица sessions общая с сайтом, поэтому «Завершить сеанс» и «Выйти везде» в личном
кабинете сразу отключают и клиент мессенджера.
"""
import time

import aiosqlite
import grpc

from auth_core.config import settings
from auth_core.db import fetch_one
from auth_core.security import token_hash

TOKEN_MAX = 128


def peer_ip(context: grpc.aio.ServicerContext) -> str:
    """'ipv4:127.0.0.1:53211' → '127.0.0.1', 'ipv6:[::1]:53211' → '::1'."""
    peer = context.peer() or ""
    kind, _, rest = peer.partition(":")
    if kind == "ipv4":
        return rest.rsplit(":", 1)[0]
    if kind == "ipv6":
        return rest.rsplit(":", 1)[0].strip("[]")
    return "unknown"


def bearer_token(context: grpc.aio.ServicerContext) -> str | None:
    for key, value in context.invocation_metadata() or ():
        if key == "authorization" and isinstance(value, str) and value.startswith("Bearer "):
            token = value[len("Bearer "):].strip()
            return token if 0 < len(token) <= TOKEN_MAX else None
    return None


async def find_session(db: aiosqlite.Connection, token: str) -> aiosqlite.Row | None:
    """Действующий сеанс по токену (те же правила, что на сайте: срок жизни и бездействие)."""
    now = int(time.time())
    return await fetch_one(db,
        """SELECT s.id AS session_id, s.last_seen_at, u.id, u.username, u.email
           FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ? AND s.expires_at > ? AND s.last_seen_at > ?""",
        (token_hash(token), now, now - settings.session_idle_hours * 3600),
    )


async def authenticate(db: aiosqlite.Connection, context: grpc.aio.ServicerContext) -> aiosqlite.Row:
    """Возвращает пользователя или обрывает вызов с UNAUTHENTICATED."""
    token = bearer_token(context)
    row = await find_session(db, token) if token else None
    if row is None:
        await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Сеанс завершён. Войдите заново.")
    now = int(time.time())
    if now - row["last_seen_at"] > 60:  # обновляем не чаще раза в минуту
        await db.execute("UPDATE sessions SET last_seen_at = ?, ip = ? WHERE id = ?",
                         (now, peer_ip(context), row["session_id"]))
    return row
