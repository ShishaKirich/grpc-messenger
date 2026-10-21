"""Выдача и проверка одноразовых кодов.

Все проверки сделаны атомарными SQL-запросами (UPDATE ... WHERE ...), поэтому
код нельзя использовать дважды, даже если два запроса придут одновременно.
"""
import time
from enum import Enum

import aiosqlite

from .config import settings
from .db import fetch_one
from .security import codes_match, generate_code, hash_code


class CheckResult(str, Enum):
    OK = "ok"
    WRONG = "wrong"            # неверный код, попытки ещё есть
    EXPIRED = "expired"        # кода нет или истёк срок
    TOO_MANY = "too_many"      # исчерпаны попытки


async def seconds_until_resend(db: aiosqlite.Connection, user_id: int, purpose: str) -> int:
    row = await fetch_one(db,
        "SELECT MAX(created_at) AS last FROM otp_codes WHERE user_id = ? AND purpose = ?",
        (user_id, purpose),
    )
    if not row or row["last"] is None:
        return 0
    return max(0, row["last"] + settings.code_resend_cooldown - int(time.time()))


async def issue_limit_reached(db: aiosqlite.Connection, user_id: int, ip: str) -> bool:
    """Лимиты на выдачу кодов за последний час.

    По IP — защита от «почтовой бомбардировки» чужих ящиков.
    По пользователю — от перебора: каждый код даёт 5 попыток, и без лимита можно
    было бы запрашивать новые коды бесконечно. С лимитом 10 кодов в час это
    максимум 50 попыток в час на миллион вариантов.
    """
    since = int(time.time()) - 3600
    by_ip = await fetch_one(db, "SELECT COUNT(*) AS n FROM otp_codes WHERE ip = ? AND created_at > ?", (ip, since))
    by_user = await fetch_one(db, "SELECT COUNT(*) AS n FROM otp_codes WHERE user_id = ? AND created_at > ?",
                              (user_id, since))
    return by_ip["n"] >= settings.codes_per_ip_per_hour or by_user["n"] >= settings.codes_per_user_per_hour


async def issue_code(db: aiosqlite.Connection, user_id: int, purpose: str, ip: str,
                     payload: str | None = None) -> str:
    """Создаёт новый код и возвращает его (отправка письма — забота вызывающего).

    Старые коды гасить отдельно не нужно: check_code проверяет только самый свежий.
    """
    now = int(time.time())
    code = generate_code()
    await db.execute(
        """INSERT INTO otp_codes (user_id, purpose, code_hash, payload, ip, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, purpose, hash_code(code), payload, ip, now, now + settings.code_ttl_seconds),
    )
    return code


async def check_code(db: aiosqlite.Connection, user_id: int, purpose: str,
                     code: str) -> tuple[CheckResult, str | None]:
    """Проверяет код. Возвращает результат и payload кода (если он верный)."""
    now = int(time.time())
    row = await fetch_one(db,
        """SELECT id, code_hash, payload, attempts, used, expires_at FROM otp_codes
           WHERE user_id = ? AND purpose = ?
           ORDER BY id DESC LIMIT 1""",
        (user_id, purpose),
    )
    # Действует только самый последний код: если запросили новый, старые уже не подходят.
    if row is None or row["used"] or row["expires_at"] <= now:
        return CheckResult.EXPIRED, None

    # Сначала засчитываем попытку, и только потом сравниваем код.
    cur = await db.execute(
        "UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ? AND used = 0 AND attempts < ?",
        (row["id"], settings.code_max_attempts),
    )
    if cur.rowcount == 0:
        return CheckResult.TOO_MANY, None

    if not codes_match(code.strip(), row["code_hash"]):
        if row["attempts"] + 1 >= settings.code_max_attempts:
            return CheckResult.TOO_MANY, None
        return CheckResult.WRONG, None

    cur = await db.execute("UPDATE otp_codes SET used = 1 WHERE id = ? AND used = 0", (row["id"],))
    if cur.rowcount != 1:
        return CheckResult.EXPIRED, None
    return CheckResult.OK, row["payload"]
