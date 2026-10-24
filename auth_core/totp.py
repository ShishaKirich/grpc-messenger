"""Второй фактор через приложение-аутентификатор (TOTP, RFC 6238) и резервные коды.

Как это работает: сервер и телефон знают общий секрет. Каждые 30 секунд обе
стороны вычисляют из секрета и текущего времени шестизначный код. Если коды
совпали, значит пользователь держит в руках телефон с этим секретом.
"""
import base64
import hashlib
import hmac
import secrets
import time

import aiosqlite
import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken

from .config import settings
from .db import fetch_one
from .security import hash_code

STEP = 30            # длина интервала в секундах
VALID_WINDOW = 1     # принимаем код из соседних интервалов: запас на расхождение часов ±30 с
BACKUP_CODES_COUNT = 10
BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # без похожих символов (0/o, 1/l/i)

# Секрет TOTP хранится в базе зашифрованным (AES через Fernet). Ключ выводится из SECRET_KEY,
# поэтому утечка одной только базы не даёт сгенерировать коды.
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"totp-secret:" + settings.secret_key.encode()).digest()))


def new_secret() -> str:
    return pyotp.random_base32()  # 160 бит, как рекомендует RFC 4226


def encrypt(secret: str) -> str:
    return _fernet.encrypt(secret.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        return None  # например, сменили SECRET_KEY


def provisioning_uri(secret: str, email: str) -> str:
    """Ссылка otpauth://, которую приложение читает из QR-кода."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.app_name)


def qr_data_uri(uri: str) -> str:
    """QR-код в виде SVG прямо в странице: секрет не уходит ни в какие внешние сервисы."""
    return segno.make(uri, error="m").svg_data_uri(scale=6, border=2, dark="#0b1020", light="#ffffff")


def format_secret(secret: str) -> str:
    """Секрет группами по 4 символа — для ручного ввода, если камера не работает."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """Номер интервала, которому соответствует код, или None, если код неверный."""
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    now = time.time() if now is None else now
    totp = pyotp.TOTP(secret)
    for offset in range(-VALID_WINDOW, VALID_WINDOW + 1):
        moment = now + offset * STEP
        if hmac.compare_digest(totp.at(moment), code):
            return int(moment // STEP)
    return None


async def verify_and_consume(db: aiosqlite.Connection, user: aiosqlite.Row, code: str,
                             secret: str | None = None) -> bool:
    """Проверяет код приложения. Каждый код принимается только один раз.

    Защита от повторного использования: запоминаем номер последнего принятого
    интервала и принимаем только более новые. Условие в UPDATE делает проверку
    атомарной, так что один и тот же код не пройдёт даже в двух одновременных запросах.
    """
    secret = secret or (decrypt(user["totp_secret"]) if user["totp_secret"] else None)
    if not secret:
        return False
    step = matching_step(secret, code)
    if step is None:
        return False
    cur = await db.execute(
        "UPDATE users SET totp_last_step = ? WHERE id = ? AND (totp_last_step IS NULL OR totp_last_step < ?)",
        (step, user["id"], step),
    )
    return cur.rowcount == 1


# ---------- резервные коды ----------

def _normalize_backup(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def looks_like_backup_code(code: str) -> bool:
    c = _normalize_backup(code)
    return len(c) == 8 and all(ch in BACKUP_ALPHABET for ch in c)


async def create_backup_codes(db: aiosqlite.Connection, user_id: int) -> list[str]:
    """Создаёт новый набор резервных кодов (старые удаляются). Коды показываются один раз."""
    codes = ["".join(secrets.choice(BACKUP_ALPHABET) for _ in range(8)) for _ in range(BACKUP_CODES_COUNT)]
    await db.execute("DELETE FROM backup_codes WHERE user_id = ?", (user_id,))
    for code in codes:
        await db.execute("INSERT INTO backup_codes (user_id, code_hash) VALUES (?, ?)",
                         (user_id, hash_code("backup:" + code)))
    return [f"{c[:4]}-{c[4:]}" for c in codes]


async def use_backup_code(db: aiosqlite.Connection, user_id: int, code: str) -> bool:
    cur = await db.execute(
        "UPDATE backup_codes SET used_at = ? WHERE user_id = ? AND code_hash = ? AND used_at IS NULL",
        (int(time.time()), user_id, hash_code("backup:" + _normalize_backup(code))),
    )
    return cur.rowcount == 1


async def backup_codes_left(db: aiosqlite.Connection, user_id: int) -> int:
    row = await fetch_one(db, "SELECT COUNT(*) AS n FROM backup_codes WHERE user_id = ? AND used_at IS NULL", (user_id,))
    return row["n"]
