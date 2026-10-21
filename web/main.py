"""Веб-приложение: регистрация, вход по паролю и второй фактор — код из письма."""
import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import aiosqlite
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTasks
from starlette.middleware.sessions import SessionMiddleware

from auth_core import login_log, mailer, otp, totp
from auth_core.login_log import recent_failures
from auth_core.config import settings
from auth_core.db import connect, fetch_all, fetch_one, get_db, init_db
from auth_core.passwords import validate_new_password
from auth_core.security import csrf_token, csrf_valid, describe_user_agent, hash_password, verify_password

from . import sessions
from .sessions import client_ip, user_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

BASE_DIR = Path(__file__).parent
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
# Имя пользователя — публичный логин в мессенджере. Только латиница, цифры и «_»:
# так нельзя завести «аlice» с кириллической «а» и выдать себя за alice.
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
PENDING_TTL = 15 * 60      # сколько живёт незавершённый вход/регистрация в сессии
RESET_TTL = 10 * 60        # сколько есть времени задать новый пароль после ввода кода
LOGGED_IN_PURPOSES = {"change_password", "change_email"}

# Ограничения длины полей: защищают от огромных запросов
EMAIL_MAX, NAME_MAX, PASSWORD_MAX, CODE_MAX = 254, 32, 256, 16


async def _periodic_cleanup():
    while True:
        await asyncio.sleep(3600)
        with suppress(Exception):
            db = await connect()
            try:
                await sessions.cleanup(db)
            finally:
                await db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.mail_backend == "smtp" and settings.secret_key.startswith("change-me"):
        raise RuntimeError("Задайте SECRET_KEY в .env перед запуском с настоящей почтой.")
    await init_db()
    task = asyncio.create_task(_periodic_cleanup())
    yield
    task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="session",
    max_age=14 * 24 * 3600,  # срок жизни сеанса на самом деле контролирует сервер (sessions.py)
    same_site="lax",
    https_only=settings.cookie_secure,
)

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data:",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"  # страницы с личными данными не кешируем
    return response


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["dt"] = lambda ts: time.strftime("%d.%m.%Y %H:%M", time.localtime(ts)) if ts else "—"
templates.env.filters["device"] = describe_user_agent


# ---------- вспомогательные функции ----------

def render(request: Request, name: str, status_code: int = 200, **ctx) -> HTMLResponse:
    ctx.update(
        app_name=settings.app_name,
        csrf=csrf_token(request.session),
        flash=request.session.pop("flash", None),
        logged_in="sid" in request.session,
        pw_min=settings.password_min_length,
    )
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def set_flash(request: Request, kind: str, text: str) -> None:
    request.session["flash"] = {"kind": kind, "text": text}


def redirect(url: str, flash: tuple[str, str] | None = None, request: Request | None = None) -> RedirectResponse:
    if flash and request is not None:
        set_flash(request, *flash)
    return RedirectResponse(url, status_code=303)


def in_background(response: RedirectResponse, coro) -> None:
    """Отправить письмо после ответа пользователю (ответ не ждёт почтовый сервер)."""
    if response.background is None:
        response.background = BackgroundTasks()
    response.background.add_task(mailer.send_in_background, coro)


def get_pending(request: Request) -> dict | None:
    """Незавершённое действие, ожидающее ввода кода."""
    pending = request.session.get("pending")
    if not pending or pending["started"] + PENDING_TTL < time.time():
        request.session.pop("pending", None)
        return None
    return pending


async def log_login(db: aiosqlite.Connection, request: Request, email: str, success: bool, method: str) -> None:
    await login_log.log_login(db, email, client_ip(request), user_agent(request), success, method)


async def get_user_by_email(db: aiosqlite.Connection, email: str) -> aiosqlite.Row | None:
    return await fetch_one(db, "SELECT * FROM users WHERE email = ?", (email,))


async def start_code_step(request: Request, db: aiosqlite.Connection, user_id: int | None, email: str,
                          purpose: str, payload: str | None = None, background: bool = False) -> RedirectResponse:
    """Выдаёт код, отправляет письмо и ведёт на страницу ввода кода.

    user_id=None — «пустышка»: email не зарегистрирован, но страница выглядит так же,
    как обычно. Так по ответам сайта нельзя узнать, есть ли у нас такой пользователь.
    background=True — письмо уходит после ответа, чтобы время ответа тоже ничего не выдавало.
    """
    request.session["pending"] = {"user_id": user_id, "email": email, "purpose": purpose,
                                  "started": int(time.time()), "fake_attempts": 0}
    response = redirect("/verify")
    if user_id is None:
        return response
    if await otp.seconds_until_resend(db, user_id, purpose) > 0:
        return response  # код уже недавно отправлен, на странице будет таймер
    if await otp.issue_limit_reached(db, user_id, client_ip(request)):
        return redirect("/verify", ("error", "Слишком много запросов кода. Попробуйте через час."), request)

    code = await otp.issue_code(db, user_id, purpose, client_ip(request), payload)
    if background:
        in_background(response, mailer.send_code(email, code, purpose))
        return response
    try:
        await mailer.send_code(email, code, purpose)
    except Exception:
        log.exception("Не удалось отправить письмо на %s", email)
        return redirect("/verify", ("error", "Не удалось отправить письмо. Попробуйте отправить код ещё раз."), request)
    return response


async def complete_login(request: Request, db: aiosqlite.Connection, user: aiosqlite.Row, method: str,
                         trust: bool = False, alert_new_device: bool = True, welcome: str = "Вы успешно вошли.") -> RedirectResponse:
    """Финальный шаг входа: запоминаем устройство, создаём сеанс, пишем журнал."""
    response = redirect("/dashboard")
    is_new_device = await sessions.remember_device(db, request, response, user["id"], trust)
    await sessions.create_session(db, request, user["id"])
    await db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (int(time.time()), user["id"]))
    await log_login(db, request, user["email"], True, method)
    set_flash(request, "success", welcome)

    if is_new_device and alert_new_device:
        in_background(response, mailer.send_notice(user["email"], "Вход с нового устройства", [
            f"Здравствуйте, {user['username']}!",
            f"В ваш аккаунт выполнен вход с нового устройства: {describe_user_agent(user_agent(request))}, "
            f"IP {client_ip(request)}, {time.strftime('%d.%m.%Y %H:%M')}.",
            "Если это были вы, ничего делать не нужно.",
            "Если нет — смените пароль и завершите чужие сеансы в личном кабинете.",
        ]))
    return response


async def password_changed(db: aiosqlite.Connection, user: aiosqlite.Row, new_hash: str,
                           keep_session_id: int | None) -> None:
    """Меняет пароль и отзывает всё, что было выдано по старому: сеансы и доверие устройствам."""
    await db.execute("UPDATE users SET password_hash = ?, password_changed_at = ? WHERE id = ?",
                     (new_hash, int(time.time()), user["id"]))
    await sessions.delete_other_sessions(db, user["id"], keep_session_id)
    await sessions.untrust_all_devices(db, user["id"])


def password_notice(user: aiosqlite.Row, request: Request):
    return mailer.send_notice(user["email"], "Пароль изменён", [
        f"Здравствуйте, {user['username']}!",
        f"Пароль от вашего аккаунта был изменён {time.strftime('%d.%m.%Y %H:%M')} (IP {client_ip(request)}).",
        "Все остальные сеансы завершены, доверие ко всем устройствам отозвано.",
        "Если это сделали не вы, срочно восстановите доступ через «Забыли пароль?».",
    ])


# ---------- главная ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render(request, "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ---------- регистрация ----------

@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return render(request, "register.html", form={})


@app.post("/register")
async def register(
    request: Request,
    username: str = Form(..., max_length=NAME_MAX * 4),
    email: str = Form(..., max_length=EMAIL_MAX),
    password: str = Form(..., max_length=PASSWORD_MAX),
    password2: str = Form(..., max_length=PASSWORD_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    username, email = username.strip(), email.strip().lower()
    form = {"username": username, "email": email}

    def error(text: str):
        return render(request, "register.html", 400, form=form, error=text)

    if not csrf_valid(request.session, csrf):
        return error("Сессия устарела, обновите страницу.")
    if not USERNAME_RE.match(username):
        return error("Имя пользователя: от 3 до 32 символов, латинские буквы, цифры и «_».")
    if not EMAIL_RE.match(email):
        return error("Введите корректный email.")
    if problem := await validate_new_password(password, password2, [username, email]):
        return error(problem)

    pw_hash = await hash_password(password)
    existing = await get_user_by_email(db, email)
    if existing and existing["email_verified"]:
        # Не говорим «email занят» — это раскрыло бы, кто у нас зарегистрирован.
        # Показываем ту же страницу ввода кода, а владельцу адреса тихо сообщаем о попытке.
        response = await start_code_step(request, db, None, email, "verify_email")
        in_background(response, mailer.send_notice(email, "Попытка регистрации", [
            "Кто-то попытался зарегистрировать новый аккаунт на ваш адрес.",
            "Ваш аккаунт уже существует, ничего не изменилось. Если забыли пароль, воспользуйтесь «Забыли пароль?».",
        ]))
        return response

    taken = await fetch_one(db, "SELECT email FROM users WHERE username = ? COLLATE NOCASE", (username,))
    if taken and taken["email"] != email:
        # Имена публичные (по ним ищут друзей в мессенджере), поэтому сказать «занято» безопасно.
        return error("Это имя пользователя уже занято, выберите другое.")

    if existing:
        # Регистрация была начата, но почта не подтверждена: обновляем данные и шлём код заново.
        await db.execute("UPDATE users SET username = ?, password_hash = ? WHERE id = ?",
                         (username, pw_hash, existing["id"]))
        user_id = existing["id"]
    else:
        try:
            cur = await db.execute(
                "INSERT INTO users (email, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (email, username, pw_hash, int(time.time())),
            )
        except aiosqlite.IntegrityError:  # тот же email или имя заняли в соседнем запросе
            if await fetch_one(db, "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)):
                return error("Это имя пользователя уже занято, выберите другое.")
            return await start_code_step(request, db, None, email, "verify_email")
        user_id = cur.lastrowid
    return await start_code_step(request, db, user_id, email, "verify_email", background=True)


# ---------- вход ----------

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if "sid" in request.session:
        return redirect("/dashboard")
    return render(request, "login.html", form={})


@app.post("/login")
async def login(
    request: Request,
    email: str = Form(..., max_length=EMAIL_MAX),
    password: str = Form(..., max_length=PASSWORD_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    email = email.strip().lower()
    form = {"email": email}
    if not csrf_valid(request.session, csrf):
        return render(request, "login.html", 400, form=form, error="Сессия устарела, обновите страницу.")

    if await recent_failures(db, email) >= settings.login_max_failures:
        minutes = settings.login_window_seconds // 60
        return render(request, "login.html", 429, form=form,
                      error=f"Слишком много неудачных попыток. Попробуйте через {minutes} минут.")

    user = await get_user_by_email(db, email)
    if not await verify_password(user["password_hash"] if user else None, password):
        await log_login(db, request, email, False, "password_fail")
        return render(request, "login.html", 401, form=form, error="Неверный email или пароль.")

    # Пароль верный — первый фактор пройден.
    if not user["email_verified"]:
        return await start_code_step(request, db, user["id"], user["email"], "verify_email")
    if await sessions.is_trusted_device(db, request, user["id"]):
        return await complete_login(request, db, user, "trusted_device")
    # Второй фактор: код из приложения, если оно подключено, иначе код на почту.
    if user["totp_enabled"]:
        return start_totp_step(request, user)
    return await start_code_step(request, db, user["id"], user["email"], "login")


def start_totp_step(request: Request, user: aiosqlite.Row) -> RedirectResponse:
    """Код из приложения генерирует телефон, поэтому ничего не отправляем — сразу на страницу ввода."""
    request.session["pending"] = {"user_id": user["id"], "email": user["email"], "purpose": "totp",
                                  "started": int(time.time()), "fake_attempts": 0}
    return redirect("/verify")


# ---------- восстановление пароля ----------

@app.get("/forgot", response_class=HTMLResponse)
async def forgot_form(request: Request):
    return render(request, "forgot.html", form={})


@app.post("/forgot")
async def forgot(
    request: Request,
    email: str = Form(..., max_length=EMAIL_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    email = email.strip().lower()
    if not csrf_valid(request.session, csrf):
        return render(request, "forgot.html", 400, form={"email": email}, error="Сессия устарела, обновите страницу.")
    if not EMAIL_RE.match(email):
        return render(request, "forgot.html", 400, form={"email": email}, error="Введите корректный email.")
    user = await get_user_by_email(db, email)
    # Ответ одинаковый, есть такой email или нет, а письмо уходит в фоне.
    return await start_code_step(request, db, user["id"] if user else None, email, "reset", background=True)


@app.get("/reset", response_class=HTMLResponse)
async def reset_form(request: Request):
    reset = request.session.get("reset")
    if not reset or reset["until"] < time.time():
        return redirect("/forgot", ("error", "Сначала подтвердите email кодом."), request)
    return render(request, "reset.html")


@app.post("/reset")
async def reset(
    request: Request,
    password: str = Form(..., max_length=PASSWORD_MAX),
    password2: str = Form(..., max_length=PASSWORD_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    reset_state = request.session.get("reset")
    if not reset_state or reset_state["until"] < time.time():
        return redirect("/forgot", ("error", "Время вышло, запросите код заново."), request)
    if not csrf_valid(request.session, csrf):
        return render(request, "reset.html", 400, error="Сессия устарела, обновите страницу.")
    user = await fetch_one(db, "SELECT * FROM users WHERE id = ?", (reset_state["user_id"],))
    if user is None:
        return redirect("/forgot")
    if problem := await validate_new_password(password, password2, [user["username"], user["email"]]):
        return render(request, "reset.html", 400, error=problem)

    await password_changed(db, user, await hash_password(password), keep_session_id=None)
    await db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))  # код пришёл на эту почту
    if user["totp_enabled"]:
        # Сброс пароля по почте не должен обходить приложение-аутентификатор:
        # иначе взлом почты снова давал бы полный доступ к аккаунту.
        request.session.clear()
        response = start_totp_step(request, user)
        set_flash(request, "success", "Пароль изменён. Для входа введите код из приложения.")
        in_background(response, password_notice(user, request))
        return response
    response = await complete_login(request, db, user, "reset", alert_new_device=False,
                                    welcome="Пароль изменён, все другие сеансы завершены.")
    in_background(response, password_notice(user, request))
    return response


# ---------- ввод кода ----------

@app.get("/verify", response_class=HTMLResponse)
async def verify_form(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    pending = get_pending(request)
    if not pending:
        return redirect("/login", ("error", "Сначала войдите или зарегистрируйтесь."), request)
    wait = 0
    if pending["user_id"] is not None and pending["purpose"] != "totp":
        wait = await otp.seconds_until_resend(db, pending["user_id"], pending["purpose"])
    return render(request, "verify.html", email=pending["email"], purpose=pending["purpose"], resend_wait=wait,
                  can_trust=pending["purpose"] in ("login", "verify_email", "totp"),
                  cancel_url="/settings" if pending["purpose"] in LOGGED_IN_PURPOSES else "/login")


@app.post("/verify")
async def verify(
    request: Request,
    code: str = Form(..., max_length=CODE_MAX),
    trust: str = Form(""),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    pending = get_pending(request)
    if not pending:
        return redirect("/login", ("error", "Время на ввод кода вышло. Начните заново."), request)
    if not csrf_valid(request.session, csrf):
        return redirect("/verify", ("error", "Сессия устарела, попробуйте ещё раз."), request)

    purpose = pending["purpose"]
    if purpose == "totp":
        return await verify_totp_login(request, db, pending, code, bool(trust))
    if pending["user_id"] is None:
        # «Пустышка» ведёт себя как настоящий код: 5 попыток, потом блокировка
        pending["fake_attempts"] += 1
        request.session["pending"] = pending
        result, payload = (otp.CheckResult.TOO_MANY if pending["fake_attempts"] >= settings.code_max_attempts
                           else otp.CheckResult.WRONG), None
    else:
        result, payload = await otp.check_code(db, pending["user_id"], purpose, code)

    if result is otp.CheckResult.WRONG:
        return redirect("/verify", ("error", "Неверный код."), request)
    if result is otp.CheckResult.TOO_MANY:
        return redirect("/verify", ("error", "Слишком много неверных попыток. Запросите новый код."), request)
    if result is otp.CheckResult.EXPIRED:
        return redirect("/verify", ("error", "Код истёк. Запросите новый."), request)

    user = await fetch_one(db, "SELECT * FROM users WHERE id = ?", (pending["user_id"],))
    if user is None:
        request.session.pop("pending", None)
        return redirect("/login")
    request.session.pop("pending", None)

    if purpose == "verify_email":
        await db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))
        return await complete_login(request, db, user, "otp", trust=bool(trust), alert_new_device=False,
                                    welcome="Почта подтверждена, добро пожаловать!")
    if purpose == "login":
        return await complete_login(request, db, user, "otp", trust=bool(trust))
    if purpose == "reset":
        request.session["reset"] = {"user_id": user["id"], "until": int(time.time()) + RESET_TTL}
        return redirect("/reset")

    # Остальные действия выполняются из личного кабинета: сеанс должен быть тем же пользователем
    auth = await sessions.current_user(db, request)
    if auth is None or auth[0]["id"] != user["id"]:
        return redirect("/login", ("error", "Сеанс завершён. Войдите заново."), request)
    _, session_id = auth

    if purpose == "change_password":
        await password_changed(db, user, payload, keep_session_id=session_id)
        response = redirect("/settings", ("success", "Пароль изменён. Остальные сеансы завершены."), request)
        in_background(response, password_notice(user, request))
        return response

    if purpose == "change_email":
        old_email = user["email"]
        try:
            await db.execute("UPDATE users SET email = ?, email_verified = 1 WHERE id = ?", (payload, user["id"]))
        except aiosqlite.IntegrityError:
            return redirect("/settings", ("error", "Этот email уже занят другим аккаунтом."), request)
        response = redirect("/settings", ("success", f"Email изменён на {payload}."), request)
        in_background(response, mailer.send_notice(old_email, "Email аккаунта изменён", [
            f"Здравствуйте, {user['username']}!",
            f"Email вашего аккаунта изменён на {payload} ({time.strftime('%d.%m.%Y %H:%M')}, IP {client_ip(request)}).",
            "Если это сделали не вы, срочно свяжитесь с поддержкой.",
        ]))
        return response

    return redirect("/")


@app.post("/verify/resend")
async def resend(request: Request, csrf: str = Form("", max_length=100), db: aiosqlite.Connection = Depends(get_db)):
    pending = get_pending(request)
    if not pending:
        return redirect("/login", ("error", "Время на ввод кода вышло. Начните заново."), request)
    if not csrf_valid(request.session, csrf):
        return redirect("/verify", ("error", "Сессия устарела, попробуйте ещё раз."), request)
    if pending["user_id"] is None:
        return redirect("/verify", ("success", "Новый код отправлен."), request)
    if pending["purpose"] == "totp":
        return redirect("/verify")  # код из приложения не отправляется

    wait = await otp.seconds_until_resend(db, pending["user_id"], pending["purpose"])
    if wait > 0:
        return redirect("/verify", ("error", f"Новый код можно запросить через {wait} с."), request)
    if await otp.issue_limit_reached(db, pending["user_id"], client_ip(request)):
        return redirect("/verify", ("error", "Слишком много запросов кода. Попробуйте через час."), request)
    # payload берём из последнего кода: при смене email/пароля он должен сохраниться
    last = await fetch_one(db,
        "SELECT payload FROM otp_codes WHERE user_id = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
        (pending["user_id"], pending["purpose"]),
    )
    code = await otp.issue_code(db, pending["user_id"], pending["purpose"], client_ip(request),
                                last["payload"] if last else None)
    try:
        await mailer.send_code(pending["email"], code, pending["purpose"])
    except Exception:
        log.exception("Не удалось отправить письмо на %s", pending["email"])
        return redirect("/verify", ("error", "Не удалось отправить письмо. Попробуйте позже."), request)
    return redirect("/verify", ("success", "Новый код отправлен."), request)


@app.post("/verify/cancel")
async def cancel_verify(request: Request, csrf: str = Form("", max_length=100)):
    pending = get_pending(request)
    if csrf_valid(request.session, csrf):
        request.session.pop("pending", None)
    if pending and pending["purpose"] in LOGGED_IN_PURPOSES:
        return redirect("/settings")
    return redirect("/login")


async def verify_totp_login(request: Request, db: aiosqlite.Connection, pending: dict, code: str,
                            trust: bool) -> RedirectResponse:
    """Второй шаг входа для тех, у кого подключено приложение: код из приложения или резервный код."""
    user = await fetch_one(db, "SELECT * FROM users WHERE id = ?", (pending["user_id"],))
    if user is None or not user["totp_enabled"]:
        request.session.pop("pending", None)
        return redirect("/login")
    # Неверные коды считаются вместе с неверными паролями: 5 ошибок за 15 минут — блокировка
    if await recent_failures(db, user["email"]) >= settings.login_max_failures:
        minutes = settings.login_window_seconds // 60
        return redirect("/verify", ("error", f"Слишком много неверных попыток. Попробуйте через {minutes} минут."), request)

    if totp.looks_like_backup_code(code):
        method, ok = "backup_code", await totp.use_backup_code(db, user["id"], code)
    else:
        method, ok = "totp", await totp.verify_and_consume(db, user, code)
    if not ok:
        await log_login(db, request, user["email"], False, "totp_fail")
        return redirect("/verify", ("error", "Неверный код."), request)

    request.session.pop("pending", None)
    response = await complete_login(request, db, user, method, trust=trust)
    if method == "backup_code":
        left = await totp.backup_codes_left(db, user["id"])
        set_flash(request, "success" if left > 2 else "error",
                  f"Вы вошли по резервному коду. Осталось кодов: {left}."
                  + (" Создайте новые в настройках." if left <= 2 else ""))
        in_background(response, mailer.send_notice(user["email"], "Использован резервный код", [
            f"Здравствуйте, {user['username']}!",
            f"Для входа использован резервный код ({time.strftime('%d.%m.%Y %H:%M')}, IP {client_ip(request)}). "
            f"Осталось кодов: {left}.",
            "Если это были не вы, смените пароль и завершите чужие сеансы.",
        ]))
    return response


# ---------- личный кабинет ----------

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user, session_id = auth
    return render(
        request, "dashboard.html", user=user, current_session_id=session_id,
        sessions=await sessions.list_sessions(db, user["id"]),
        devices=await sessions.list_trusted_devices(db, user["id"]),
        events=await fetch_all(db,
            "SELECT ip, user_agent, success, method, created_at FROM login_events WHERE email = ? ORDER BY id DESC LIMIT 10",
            (user["email"],)),
    )


@app.post("/sessions/{session_id}/revoke")
async def revoke_session(session_id: int, request: Request, csrf: str = Form("", max_length=100),
                         db: aiosqlite.Connection = Depends(get_db)):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    if csrf_valid(request.session, csrf):
        await sessions.delete_session(db, auth[0]["id"], session_id)
        if session_id == auth[1]:
            request.session.clear()
            return redirect("/login", ("success", "Вы вышли из аккаунта."), request)
        set_flash(request, "success", "Сеанс завершён.")
    return redirect("/dashboard")


@app.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request, csrf: str = Form("", max_length=100),
                                db: aiosqlite.Connection = Depends(get_db)):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    if csrf_valid(request.session, csrf):
        await sessions.delete_other_sessions(db, auth[0]["id"], auth[1])
        set_flash(request, "success", "Все остальные сеансы завершены.")
    return redirect("/dashboard")


@app.post("/devices/{device_id}/untrust")
async def untrust_device(device_id: int, request: Request, csrf: str = Form("", max_length=100),
                         db: aiosqlite.Connection = Depends(get_db)):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    if csrf_valid(request.session, csrf):
        await sessions.untrust_device(db, auth[0]["id"], device_id)
        set_flash(request, "success", "Устройство больше не считается доверенным.")
    return redirect("/dashboard")


# ---------- настройки ----------

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    return render(request, "settings.html", user=auth[0], backup_left=await totp.backup_codes_left(db, auth[0]["id"]))


async def check_current_password(db, request, user, password) -> str | None:
    if await recent_failures(db, user["email"]) >= settings.login_max_failures:
        return "Слишком много неверных паролей. Попробуйте позже."
    if not await verify_password(user["password_hash"], password):
        await log_login(db, request, user["email"], False, "password_fail")
        return "Текущий пароль указан неверно."
    return None


@app.post("/settings/password")
async def change_password(
    request: Request,
    current_password: str = Form(..., max_length=PASSWORD_MAX),
    password: str = Form(..., max_length=PASSWORD_MAX),
    password2: str = Form(..., max_length=PASSWORD_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user = auth[0]

    def error(text):
        return render(request, "settings.html", 400, user=user, pw_error=text)

    if not csrf_valid(request.session, csrf):
        return error("Сессия устарела, обновите страницу.")
    if problem := await check_current_password(db, request, user, current_password):
        return error(problem)
    if problem := await validate_new_password(password, password2, [user["username"], user["email"]]):
        return error(problem)
    if await verify_password(user["password_hash"], password):
        return error("Новый пароль совпадает со старым.")
    # Новый пароль применится только после ввода кода; до этого его хеш лежит в записи кода
    return await start_code_step(request, db, user["id"], user["email"], "change_password",
                                 payload=await hash_password(password))


@app.post("/settings/email")
async def change_email(
    request: Request,
    new_email: str = Form(..., max_length=EMAIL_MAX),
    current_password: str = Form(..., max_length=PASSWORD_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user = auth[0]
    new_email = new_email.strip().lower()

    def error(text):
        return render(request, "settings.html", 400, user=user, email_error=text, new_email=new_email)

    if not csrf_valid(request.session, csrf):
        return error("Сессия устарела, обновите страницу.")
    if not EMAIL_RE.match(new_email):
        return error("Введите корректный email.")
    if new_email == user["email"].lower():
        return error("Это ваш текущий email.")
    if problem := await check_current_password(db, request, user, current_password):
        return error(problem)
    # Код отправляем на НОВЫЙ адрес: так пользователь доказывает, что владеет им
    return await start_code_step(request, db, user["id"], new_email, "change_email", payload=new_email)


# ---------- приложение-аутентификатор ----------

@app.post("/settings/totp/start")
async def totp_start(
    request: Request,
    current_password: str = Form(..., max_length=PASSWORD_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user = auth[0]
    backup_left = await totp.backup_codes_left(db, user["id"])
    if not csrf_valid(request.session, csrf):
        return render(request, "settings.html", 400, user=user, backup_left=backup_left, totp_error="Сессия устарела.")
    if user["totp_enabled"]:
        return redirect("/settings")
    if problem := await check_current_password(db, request, user, current_password):
        return render(request, "settings.html", 400, user=user, backup_left=backup_left, totp_error=problem)
    # Секрет сохраняем сразу (зашифрованным), но включаем защиту только после ввода кода
    await db.execute("UPDATE users SET totp_secret = ?, totp_last_step = NULL WHERE id = ?",
                     (totp.encrypt(totp.new_secret()), user["id"]))
    return redirect("/settings/totp")


@app.get("/settings/totp", response_class=HTMLResponse)
async def totp_setup_page(request: Request, db: aiosqlite.Connection = Depends(get_db)):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    return render_totp_setup(request, auth[0])


def render_totp_setup(request: Request, user: aiosqlite.Row, error: str | None = None):
    """Страница с QR-кодом. Секрет показывается, пока подключение не подтверждено кодом."""
    secret = totp.decrypt(user["totp_secret"]) if user["totp_secret"] else None
    if user["totp_enabled"] or not secret:
        return redirect("/settings")
    return render(request, "totp_setup.html", qr=totp.qr_data_uri(totp.provisioning_uri(secret, user["email"])),
                  secret=totp.format_secret(secret), error=error)


@app.post("/settings/totp/confirm", response_class=HTMLResponse)
async def totp_confirm(
    request: Request,
    code: str = Form(..., max_length=CODE_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user = auth[0]
    if user["totp_enabled"] or not user["totp_secret"]:
        return redirect("/settings")
    if not csrf_valid(request.session, csrf):
        return render_totp_setup(request, user, "Сессия устарела, попробуйте ещё раз.")
    # Код подтверждает, что приложение настроено правильно и часы на телефоне идут верно
    if not await totp.verify_and_consume(db, user, code):
        return render_totp_setup(request, user, "Код не подошёл. Проверьте время на телефоне и введите новый код.")

    await db.execute("UPDATE users SET totp_enabled = 1 WHERE id = ?", (user["id"],))
    codes = await totp.create_backup_codes(db, user["id"])
    response = render(request, "totp_backup.html", codes=codes, just_enabled=True)
    response.background = BackgroundTasks()
    response.background.add_task(mailer.send_in_background, mailer.send_notice(user["email"], "Подключено приложение-аутентификатор", [
        f"Здравствуйте, {user['username']}!",
        f"К вашему аккаунту подключено приложение-аутентификатор ({time.strftime('%d.%m.%Y %H:%M')}, IP {client_ip(request)}).",
        "Теперь при входе нужен код из приложения. Если это сделали не вы, срочно смените пароль.",
    ]))
    return response


async def check_totp_or_backup(db, request, user, code) -> str | None:
    """Подтверждение опасных действий кодом из приложения (или резервным кодом)."""
    if await recent_failures(db, user["email"]) >= settings.login_max_failures:
        return "Слишком много неверных попыток. Попробуйте позже."
    if totp.looks_like_backup_code(code):
        ok = await totp.use_backup_code(db, user["id"], code)
    else:
        ok = await totp.verify_and_consume(db, user, code)
    if not ok:
        await log_login(db, request, user["email"], False, "totp_fail")
        return "Неверный код из приложения."
    return None


@app.post("/settings/totp/backup-codes", response_class=HTMLResponse)
async def totp_new_backup_codes(
    request: Request,
    code: str = Form(..., max_length=CODE_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user = auth[0]
    backup_left = await totp.backup_codes_left(db, user["id"])
    if not user["totp_enabled"]:
        return redirect("/settings")
    if not csrf_valid(request.session, csrf):
        return render(request, "settings.html", 400, user=user, backup_left=backup_left, totp_error="Сессия устарела.")
    if problem := await check_totp_or_backup(db, request, user, code):
        return render(request, "settings.html", 400, user=user, backup_left=backup_left, totp_error=problem)
    return render(request, "totp_backup.html", codes=await totp.create_backup_codes(db, user["id"]), just_enabled=False)


@app.post("/settings/totp/disable")
async def totp_disable(
    request: Request,
    current_password: str = Form(..., max_length=PASSWORD_MAX),
    code: str = Form(..., max_length=CODE_MAX),
    csrf: str = Form("", max_length=100),
    db: aiosqlite.Connection = Depends(get_db),
):
    auth = await sessions.current_user(db, request)
    if auth is None:
        return redirect("/login")
    user = auth[0]
    backup_left = await totp.backup_codes_left(db, user["id"])
    if not user["totp_enabled"]:
        return redirect("/settings")
    if not csrf_valid(request.session, csrf):
        return render(request, "settings.html", 400, user=user, backup_left=backup_left, totp_error="Сессия устарела.")
    # Отключение защиты — опасное действие: нужны и пароль, и код из приложения
    problem = (await check_current_password(db, request, user, current_password)
               or await check_totp_or_backup(db, request, user, code))
    if problem:
        return render(request, "settings.html", 400, user=user, backup_left=backup_left, totp_error=problem)

    await db.execute("UPDATE users SET totp_enabled = 0, totp_secret = NULL, totp_last_step = NULL WHERE id = ?",
                     (user["id"],))
    await db.execute("DELETE FROM backup_codes WHERE user_id = ?", (user["id"],))
    response = redirect("/settings", ("success", "Приложение-аутентификатор отключено. Второй фактор — код на почту."), request)
    in_background(response, mailer.send_notice(user["email"], "Приложение-аутентификатор отключено", [
        f"Здравствуйте, {user['username']}!",
        f"Приложение-аутентификатор отключено ({time.strftime('%d.%m.%Y %H:%M')}, IP {client_ip(request)}). "
        "Теперь второй фактор — код на почту.",
        "Если это сделали не вы, срочно смените пароль и завершите чужие сеансы.",
    ]))
    return response


@app.post("/logout")
async def logout(request: Request, csrf: str = Form("", max_length=100), db: aiosqlite.Connection = Depends(get_db)):
    if csrf_valid(request.session, csrf):
        auth = await sessions.current_user(db, request)
        if auth:
            await sessions.delete_session(db, auth[0]["id"], auth[1])
        request.session.clear()
    return redirect("/", ("success", "Вы вышли из аккаунта."), request)
