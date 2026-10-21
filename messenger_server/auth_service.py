"""Вход в мессенджер в два шага: пароль, затем второй фактор.

Шаг 1 (Login): проверяем пароль и создаём «вызов» (challenge). Клиент получает только
случайный challenge_id — без второго фактора токен сеанса не выдаётся.
Шаг 2 (VerifyCode): код с почты, из приложения-аутентификатора или резервный код.
Только после этого создаётся сеанс в общей с сайтом таблице sessions.

Используются те же модули, что и на сайте (auth_core): Argon2id, одноразовые коды,
TOTP с защитой от повтора, журнал входов и блокировка подбора.
"""
import asyncio
import logging
import re
import time

import aiosqlite
import grpc

from auth_core import mailer, otp, totp
from auth_core.config import settings
from auth_core.db import fetch_one, opened
from auth_core.login_log import log_login, recent_failures
from auth_core.security import MESSENGER_UA_PREFIX, for_log, new_token, token_hash, verify_password
from proto import messenger_pb2 as pb
from proto import messenger_pb2_grpc as pb_grpc

from .guard import bearer_token, find_session, peer_ip

log = logging.getLogger("auth")

EMAIL_MAX, PASSWORD_MAX, CODE_MAX, DEVICE_MAX = 254, 256, 16, 64
CHALLENGE_MAX_ATTEMPTS = 5
WRONG_CREDENTIALS = "Неверный email или пароль."
# Свой тип кода: код для входа на сайт не подходит для мессенджера и наоборот
PURPOSE = "messenger_login"

_background: set[asyncio.Task] = set()


def in_background(coro) -> None:
    """Письмо-уведомление уходит после ответа клиенту: вход не ждёт почтовый сервер."""
    task = asyncio.create_task(mailer.send_in_background(coro))
    _background.add(task)  # держим ссылку, иначе задачу может собрать сборщик мусора
    task.add_done_callback(_background.discard)


def clean_device_name(name: str) -> str:
    """Название устройства пишется в журнал и показывается на сайте: только печатные символы."""
    name = re.sub(r"[^\w\s().,-]", "", name or "", flags=re.UNICODE).strip()
    return name[:DEVICE_MAX] or "компьютер"


class AuthService(pb_grpc.AuthServicer):

    async def Login(self, request: pb.LoginRequest, context: grpc.aio.ServicerContext) -> pb.LoginReply:
        email = request.email.strip().lower()
        if not email or len(email) > EMAIL_MAX or not request.password or len(request.password) > PASSWORD_MAX:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, WRONG_CREDENTIALS)
        ip, device = peer_ip(context), clean_device_name(request.device_name)
        ua = MESSENGER_UA_PREFIX + device

        async with opened() as db:
            if await recent_failures(db, email) >= settings.login_max_failures:
                minutes = settings.login_window_seconds // 60
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED,
                                    f"Слишком много неудачных попыток. Попробуйте через {minutes} минут.")

            user = await fetch_one(db, "SELECT * FROM users WHERE email = ?", (email,))
            # Для несуществующего email пароль всё равно проверяется (с хешем-заглушкой),
            # чтобы по времени ответа нельзя было понять, зарегистрирован ли адрес.
            if not await verify_password(user["password_hash"] if user else None, request.password):
                await log_login(db, email, ip, ua, False, "password_fail")
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, WRONG_CREDENTIALS)

            if not user["email_verified"]:
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION,
                                    f"Почта не подтверждена. Завершите регистрацию на сайте: {settings.web_url}")

            method = "totp" if user["totp_enabled"] else "email"
            if method == "email":
                await self._send_login_code(db, context, user, ip)

            challenge_id = new_token()
            now = int(time.time())
            expires_at = now + settings.challenge_ttl_seconds
            await db.execute(
                """INSERT INTO login_challenges (token_hash, user_id, method, device_name, ip, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (token_hash(challenge_id), user["id"], method, device, ip, now, expires_at),
            )
        return pb.LoginReply(challenge_id=challenge_id, expires_at=expires_at,
                             method=pb.TOTP if method == "totp" else pb.EMAIL_CODE)

    async def VerifyCode(self, request: pb.VerifyRequest, context: grpc.aio.ServicerContext) -> pb.VerifyReply:
        code = request.code.strip()
        if not code or len(code) > CODE_MAX:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Введите код.")

        async with opened() as db:
            challenge = await self._take_attempt(db, context, request.challenge_id)
            user = await fetch_one(db, "SELECT * FROM users WHERE id = ?", (challenge["user_id"],))
            ua = MESSENGER_UA_PREFIX + challenge["device_name"]
            ip = peer_ip(context)

            # Неверные коды считаются вместе с неверными паролями: общая блокировка подбора
            if await recent_failures(db, user["email"]) >= settings.login_max_failures:
                minutes = settings.login_window_seconds // 60
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED,
                                    f"Слишком много неверных попыток. Попробуйте через {minutes} минут.")

            if challenge["method"] == "totp":
                if totp.looks_like_backup_code(code):
                    method, ok = "backup_code", await totp.use_backup_code(db, user["id"], code)
                else:
                    method, ok = "totp", await totp.verify_and_consume(db, user, code)
                if not ok:
                    await log_login(db, user["email"], ip, ua, False, "totp_fail")
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Неверный код.")
            else:
                method = "otp"
                result, _ = await otp.check_code(db, user["id"], PURPOSE, code)
                if result is otp.CheckResult.WRONG:
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Неверный код.")
                if result is otp.CheckResult.TOO_MANY:
                    await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED,
                                        "Слишком много неверных попыток. Войдите заново.")
                if result is otp.CheckResult.EXPIRED:
                    await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Код истёк. Запросите новый.")

            # Вызов одноразовый: условие used = 0 не даст создать два сеанса по одному коду
            cur = await db.execute("UPDATE login_challenges SET used = 1 WHERE id = ? AND used = 0",
                                   (challenge["id"],))
            if cur.rowcount != 1:
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Время на ввод кода вышло. Войдите заново.")

            token = new_token()
            now = int(time.time())
            expires_at = now + settings.session_lifetime_hours * 3600
            await db.execute(
                """INSERT INTO sessions (token_hash, user_id, ip, user_agent, created_at, last_seen_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (token_hash(token), user["id"], ip, ua, now, now, expires_at),
            )
            await db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user["id"]))
            await log_login(db, user["email"], ip, ua, True, method)

        in_background(mailer.send_notice(user["email"], "Вход в мессенджер", [
            f"Здравствуйте, {user['username']}!",
            f"Выполнен вход в мессенджер: {challenge['device_name']}, IP {ip}, {time.strftime('%d.%m.%Y %H:%M')}.",
            "Если это были не вы, смените пароль и завершите чужие сеансы в личном кабинете на сайте.",
        ]))
        return pb.VerifyReply(token=token, username=user["username"], expires_at=expires_at)

    async def ResendCode(self, request: pb.ResendRequest, context: grpc.aio.ServicerContext) -> pb.Empty:
        async with opened() as db:
            challenge = await self._find_challenge(db, context, request.challenge_id)
            if challenge["method"] != "email":
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Код из приложения не отправляется по почте.")
            user = await fetch_one(db, "SELECT * FROM users WHERE id = ?", (challenge["user_id"],))
            wait = await otp.seconds_until_resend(db, user["id"], PURPOSE)
            if wait > 0:
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, f"Новый код можно запросить через {wait} с.")
            await self._send_login_code(db, context, user, peer_ip(context))
        return pb.Empty()

    async def Logout(self, request: pb.Empty, context: grpc.aio.ServicerContext) -> pb.Empty:
        token = bearer_token(context)
        if token:
            async with opened() as db:
                if await find_session(db, token):
                    await db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        return pb.Empty()

    # ---------- вспомогательное ----------

    @staticmethod
    async def _send_login_code(db: aiosqlite.Connection, context, user: aiosqlite.Row, ip: str) -> None:
        if await otp.issue_limit_reached(db, user["id"], ip):
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Слишком много запросов кода. Попробуйте через час.")
        code = await otp.issue_code(db, user["id"], PURPOSE, ip)
        try:
            await mailer.send_code(user["email"], code, PURPOSE)
        except Exception:
            log.exception("Не удалось отправить код на %s", for_log(user["email"]))
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Не удалось отправить письмо. Попробуйте позже.")

    @staticmethod
    async def _find_challenge(db: aiosqlite.Connection, context, challenge_id: str) -> aiosqlite.Row:
        row = None
        if 0 < len(challenge_id) <= 128:
            row = await fetch_one(db,
                "SELECT * FROM login_challenges WHERE token_hash = ? AND used = 0 AND expires_at > ?",
                (token_hash(challenge_id), int(time.time())),
            )
        if row is None:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Время на ввод кода вышло. Войдите заново.")
        return row

    async def _take_attempt(self, db: aiosqlite.Connection, context, challenge_id: str) -> aiosqlite.Row:
        """Засчитывает попытку ввода кода. После 5 попыток вызов сгорает, нужно войти заново."""
        row = await self._find_challenge(db, context, challenge_id)
        cur = await db.execute(
            "UPDATE login_challenges SET attempts = attempts + 1 WHERE id = ? AND used = 0 AND attempts < ?",
            (row["id"], CHALLENGE_MAX_ATTEMPTS),
        )
        if cur.rowcount != 1:
            await db.execute("UPDATE login_challenges SET used = 1 WHERE id = ?", (row["id"],))
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Слишком много неверных попыток. Войдите заново.")
        return row
