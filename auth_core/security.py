"""Пароли, одноразовые коды и CSRF-токены."""
import asyncio
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import settings

# Argon2id с параметрами из рекомендаций OWASP (19 МБ памяти, 2 прохода, 1 поток):
# надёжно против подбора и при этом ~35 мс на хеш, сервер выдерживает много входов сразу.
_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)

# Хеш-заглушка: проверяем пароль даже для несуществующего email,
# чтобы по времени ответа нельзя было понять, зарегистрирован ли адрес.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


async def hash_password(password: str) -> str:
    # Argon2 намеренно медленный и нагружает процессор, поэтому считаем его
    # в отдельном потоке, чтобы не задерживать запросы других пользователей.
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(_verify)


def generate_code() -> str:
    """Криптографически стойкий числовой код, например '048213'."""
    return "".join(secrets.choice("0123456789") for _ in range(settings.code_length))


def hash_code(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


def codes_match(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), code_hash)


def csrf_token(session: dict) -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_valid(session: dict, token: str | None) -> bool:
    expected = session.get("csrf")
    return bool(expected and token and hmac.compare_digest(expected, token))


def new_token() -> str:
    """Случайный токен для cookie сеанса или устройства (256 бит)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    # У токена 256 бит случайности, поэтому медленный хеш не нужен: SHA-256 достаточно.
    return hashlib.sha256(token.encode()).hexdigest()


# Так помечаются сеансы, открытые из клиента мессенджера (в таблице sessions колонка user_agent)
MESSENGER_UA_PREFIX = "messenger:"


def for_log(value: object, limit: int = 200) -> str:
    """Значение от пользователя для записи в лог: переводы строк и управляющие символы
    экранируются, чтобы нельзя было подделать соседние строки лога."""
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    return "".join(ch if ch.isprintable() else f"\\x{ord(ch):02x}" for ch in text)[:limit]


def describe_user_agent(ua: str | None) -> str:
    """Краткое описание устройства по заголовку User-Agent, например «Chrome, Windows»."""
    ua = ua or ""
    if ua.startswith(MESSENGER_UA_PREFIX):  # сеанс из клиента мессенджера: «Мессенджер, ПК Кирилла»
        return "Мессенджер, " + (ua[len(MESSENGER_UA_PREFIX):] or "компьютер")
    browser = next((name for key, name in [
        ("Edg/", "Edge"), ("OPR/", "Opera"), ("YaBrowser", "Яндекс Браузер"), ("Firefox/", "Firefox"),
        ("Chrome/", "Chrome"), ("Safari/", "Safari"),
    ] if key in ua), "Браузер")
    system = next((name for key, name in [
        ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
        ("Mac OS", "macOS"), ("Linux", "Linux"),
    ] if key in ua), "неизвестная ОС")
    return f"{browser}, {system}"
