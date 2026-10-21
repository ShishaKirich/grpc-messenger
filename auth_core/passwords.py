"""Проверка нового пароля: длина, стойкость (zxcvbn) и наличие в известных утечках (HIBP)."""
import asyncio
import hashlib
import logging

import httpx
from zxcvbn import zxcvbn

from .config import settings

log = logging.getLogger("passwords")

HIBP_URL = "https://api.pwnedpasswords.com/range/{prefix}"


async def breach_count(password: str) -> int | None:
    """Сколько раз пароль встречался в утечках. None — сервис недоступен.

    Используется k-анонимность: на сервер HIBP уходят только первые 5 символов
    SHA-1 хеша пароля, сам пароль и даже полный хеш никуда не передаются.
    Заголовок Add-Padding добавляет в ответ фиктивные строки, чтобы по размеру
    ответа нельзя было угадать префикс.
    """
    # SHA-1 здесь не для защиты, а потому что так устроен API HIBP
    digest = hashlib.sha1(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=settings.hibp_timeout) as client:
            resp = await client.get(HIBP_URL.format(prefix=prefix), headers={"Add-Padding": "true"})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("HIBP недоступен, проверка по утечкам пропущена: %s", exc)
        return None
    for line in resp.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate == suffix:
            return int(count)
    return 0


async def validate_new_password(password: str, password2: str, user_inputs: list[str]) -> str | None:
    """Возвращает текст ошибки или None, если пароль подходит.

    user_inputs — имя, email и т. п.: zxcvbn снижает оценку, если пароль на них похож.
    """
    if password != password2:
        return "Пароли не совпадают."
    if len(password) < settings.password_min_length:
        return f"Пароль должен быть не короче {settings.password_min_length} символов."
    if len(password) > settings.password_max_length:
        return f"Пароль должен быть не длиннее {settings.password_max_length} символов."

    inputs = [x for x in user_inputs if x]
    inputs += [x.split("@")[0] for x in inputs if "@" in x]
    # zxcvbn считает несколько миллисекунд, выносим в поток, чтобы не тормозить остальных
    result = await asyncio.to_thread(zxcvbn, password, user_inputs=inputs)
    if result["score"] < settings.password_min_score:
        return "Пароль слишком простой: его легко подобрать. Добавьте слов или воспользуйтесь генератором."

    if settings.hibp_enabled:
        count = await breach_count(password)
        if count:
            return f"Этот пароль уже встречался в утечках данных ({count:,} раз). Выберите другой.".replace(",", " ")
    return None
