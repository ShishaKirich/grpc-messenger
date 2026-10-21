"""Тесты сценариев: регистрация, вход, восстановление, смена пароля и email, сеансы, устройства."""
import os
import re

import httpx
import pytest

os.environ["DATABASE_PATH"] = "data/test.db"
os.environ["MAIL_BACKEND"] = "console"
os.environ["CODE_RESEND_COOLDOWN"] = "0"
os.environ["HIBP_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from auth_core import mailer, passwords  # noqa: E402
from web.main import app  # noqa: E402

PASSWORD = "Tr0ub4dor&3-horse-staple"
NEW_PASSWORD = "violet-Kettle-29-mirror!"
EMAIL = "kirill@example.com"

codes: list[tuple[str, str, str]] = []     # (кому, код, назначение)
notices: list[tuple[str, str]] = []        # (кому, тема)


async def fake_code(to, code, purpose):
    codes.append((to, code, purpose))


async def fake_notice(to, subject, lines):
    notices.append((to, subject))


@pytest.fixture()
def client(monkeypatch):
    if os.path.exists("data/test.db"):
        os.remove("data/test.db")
    codes.clear()
    notices.clear()
    monkeypatch.setattr(mailer, "send_code", fake_code)
    monkeypatch.setattr(mailer, "send_notice", fake_notice)
    with TestClient(app) as c:
        yield c


def new_client():
    return TestClient(app)


def csrf(client, url):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(url).text).group(1)


def register(client, email=EMAIL, password=PASSWORD, name="kirill"):
    return client.post("/register", data={
        "username": name, "email": email, "password": password, "password2": password,
        "csrf": csrf(client, "/register"),
    })


def verify(client, code=None, trust=False):
    data = {"code": code or codes[-1][1], "csrf": csrf(client, "/verify")}
    if trust:
        data["trust"] = "1"
    return client.post("/verify", data=data)


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/login", data={"email": email, "password": password, "csrf": csrf(client, "/login")})


def logout(client):
    return client.post("/logout", data={"csrf": csrf(client, "/dashboard")})


def signed_up(client):
    register(client)
    verify(client)
    return client


# ---------- регистрация и вход ----------

def test_full_flow(client):
    r = register(client)
    assert r.url.path == "/verify" and codes[-1][2] == "verify_email"
    r = verify(client)
    assert r.url.path == "/dashboard" and "Привет, kirill" in r.text

    logout(client)
    assert client.get("/dashboard").url.path == "/login"

    r = login(client, email="KIRILL@example.com")
    assert r.url.path == "/verify" and codes[-1][2] == "login"
    assert client.get("/dashboard").url.path == "/login"  # без кода в кабинет не пускает
    assert verify(client).url.path == "/dashboard"


def test_wrong_code_and_attempt_limit(client):
    register(client)
    good = codes[-1][1]
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        r = verify(client, bad)
    assert "Запросите новый код" in r.text
    assert verify(client, good).url.path == "/verify"  # правильный код уже сгорел


def test_old_code_invalid_after_resend(client):
    register(client)
    old = codes[-1][1]
    client.post("/verify/resend", data={"csrf": csrf(client, "/verify")})
    new = codes[-1][1]
    if old != new:
        assert verify(client, old).url.path == "/verify"
    assert verify(client, new).url.path == "/dashboard"


def test_code_is_single_use(client):
    signed_up(client)
    used = codes[-1][1]
    logout(client)
    login(client)
    if codes[-1][1] != used:
        assert verify(client, used).url.path == "/verify"


def test_bruteforce_lock(client):
    signed_up(client)
    logout(client)
    for _ in range(5):
        assert login(client, password="wrong-pass").status_code == 401
    assert login(client).status_code == 429


def test_csrf_required(client):
    r = client.post("/register", data={"username": "x1", "email": "a@b.cd", "password": PASSWORD, "password2": PASSWORD})
    assert r.status_code == 400


def test_register_existing_email_does_not_reveal_account(client):
    signed_up(client)
    logout(client)
    sent_before = len(codes)
    r = register(client, password=NEW_PASSWORD, name="attacker")
    assert r.url.path == "/verify"                      # выглядит как обычная регистрация
    assert len(codes) == sent_before                    # кода нет
    assert notices[-1] == (EMAIL, "Попытка регистрации")  # владельца предупредили
    assert verify(client, "123456").url.path == "/verify"
    logout(client)
    assert login(client, password=NEW_PASSWORD).status_code == 401  # старый пароль не перезаписан


# ---------- требования к паролю ----------

@pytest.mark.parametrize("weak", ["short1!", "password1234", "kirill12345", "qwertyuiop12"])
def test_weak_passwords_rejected(client, weak):
    r = register(client, password=weak)
    assert r.status_code == 400 and not codes


def test_breached_password_rejected(client, monkeypatch):
    import hashlib
    suffix = hashlib.sha1(PASSWORD.encode()).hexdigest().upper()[5:]

    def handler(request):
        assert len(request.url.path.rsplit("/", 1)[1]) == 5          # уходит только префикс хеша
        assert request.headers["Add-Padding"] == "true"
        return httpx.Response(200, text=f"0000000000000000000000000000000000A:1\n{suffix}:4242\n")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(passwords.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(passwords.settings, "hibp_enabled", True)
    r = register(client)
    assert r.status_code == 400 and "утечках" in r.text


def test_hibp_unavailable_does_not_block(client, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(passwords.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kw))
    monkeypatch.setattr(passwords.settings, "hibp_enabled", True)
    assert register(client).url.path == "/verify"


# ---------- восстановление пароля ----------

def test_password_reset(client):
    signed_up(client)
    other = new_client()
    login(other)
    verify(other)
    assert other.get("/dashboard").url.path == "/dashboard"

    logout(client)
    r = client.post("/forgot", data={"email": EMAIL, "csrf": csrf(client, "/forgot")})
    assert r.url.path == "/verify" and codes[-1][2] == "reset"
    r = verify(client)
    assert r.url.path == "/reset"
    r = client.post("/reset", data={"password": NEW_PASSWORD, "password2": NEW_PASSWORD, "csrf": csrf(client, "/reset")})
    assert r.url.path == "/dashboard"
    assert notices[-1] == (EMAIL, "Пароль изменён")
    assert other.get("/dashboard").url.path == "/login"  # чужие сеансы завершены

    logout(client)
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).url.path in ("/verify", "/dashboard")


def test_reset_unknown_email_looks_the_same(client):
    r = client.post("/forgot", data={"email": "nobody@example.com", "csrf": csrf(client, "/forgot")})
    assert r.url.path == "/verify" and not codes
    assert verify(client, "123456").url.path == "/verify"
    assert client.get("/reset").url.path == "/forgot"


def test_reset_page_requires_code(client):
    assert client.get("/reset").url.path == "/forgot"


# ---------- доверенные устройства и уведомления ----------

def test_trusted_device_skips_code(client):
    register(client)
    verify(client, trust=True)
    logout(client)
    sent_before = len(codes)
    r = login(client)
    assert r.url.path == "/dashboard" and len(codes) == sent_before
    assert "доверенное устройство" in r.text

    # С другого устройства код по-прежнему нужен
    other = new_client()
    assert login(other).url.path == "/verify"


def test_untrust_device(client):
    register(client)
    verify(client, trust=True)
    page = client.get("/dashboard").text
    device_id = re.search(r'/devices/(\d+)/untrust', page).group(1)
    client.post(f"/devices/{device_id}/untrust", data={"csrf": csrf(client, "/dashboard")})
    logout(client)
    assert login(client).url.path == "/verify"


def test_new_device_alert(client):
    signed_up(client)
    assert not any(s == "Вход с нового устройства" for _, s in notices)  # первый вход после регистрации
    other = new_client()
    login(other)
    verify(other)
    assert notices[-1] == (EMAIL, "Вход с нового устройства")
    logout(other)
    count = len(notices)
    login(other)
    verify(other)
    assert len(notices) == count  # то же устройство — без письма


# ---------- сеансы ----------

def test_revoke_other_sessions(client):
    signed_up(client)
    other = new_client()
    login(other)
    verify(other)
    client.post("/sessions/revoke-others", data={"csrf": csrf(client, "/dashboard")})
    assert other.get("/dashboard").url.path == "/login"
    assert client.get("/dashboard").url.path == "/dashboard"


def test_cannot_revoke_foreign_session(client):
    signed_up(client)
    my_ids = re.findall(r'/sessions/(\d+)/revoke', client.get("/dashboard").text)
    attacker = new_client()
    register(attacker, email="evil@example.com", name="Evil")
    verify(attacker)
    for sid in my_ids:
        attacker.post(f"/sessions/{sid}/revoke", data={"csrf": csrf(attacker, "/dashboard")})
    assert client.get("/dashboard").url.path == "/dashboard"


def test_logout_kills_session_on_server(client):
    signed_up(client)
    stolen = dict(client.cookies)
    logout(client)
    thief = new_client()
    thief.cookies.update(stolen)
    assert thief.get("/dashboard").url.path == "/login"  # украденная cookie после выхода бесполезна


# ---------- смена пароля и email ----------

def test_change_password(client):
    register(client)
    verify(client, trust=True)
    other = new_client()
    login(other)
    verify(other)

    r = client.post("/settings/password", data={
        "current_password": PASSWORD, "password": NEW_PASSWORD, "password2": NEW_PASSWORD,
        "csrf": csrf(client, "/settings")})
    assert r.url.path == "/verify" and codes[-1][2] == "change_password"
    r = verify(client)
    assert r.url.path == "/settings" and "Пароль изменён" in r.text
    assert other.get("/dashboard").url.path == "/login"
    assert client.get("/dashboard").url.path == "/dashboard"

    logout(client)
    assert login(client).status_code == 401
    assert login(client, password=NEW_PASSWORD).url.path == "/verify"  # доверие к устройству отозвано


def test_change_password_wrong_current(client):
    signed_up(client)
    r = client.post("/settings/password", data={
        "current_password": "nope", "password": NEW_PASSWORD, "password2": NEW_PASSWORD,
        "csrf": csrf(client, "/settings")})
    assert r.status_code == 400 and "неверно" in r.text


def test_change_password_not_applied_without_code(client):
    signed_up(client)
    client.post("/settings/password", data={
        "current_password": PASSWORD, "password": NEW_PASSWORD, "password2": NEW_PASSWORD,
        "csrf": csrf(client, "/settings")})
    client.post("/verify/cancel", data={"csrf": csrf(client, "/verify")})
    logout(client)
    assert login(client, password=NEW_PASSWORD).status_code == 401


def test_change_email(client):
    signed_up(client)
    r = client.post("/settings/email", data={
        "new_email": "new@example.com", "current_password": PASSWORD, "csrf": csrf(client, "/settings")})
    assert r.url.path == "/verify"
    assert codes[-1][0] == "new@example.com" and codes[-1][2] == "change_email"
    r = verify(client)
    assert "Email изменён" in r.text
    assert notices[-1] == (EMAIL, "Email аккаунта изменён")
    logout(client)
    assert login(client, email="new@example.com").url.path == "/verify"


# ---------- заголовки безопасности ----------

def test_security_headers(client):
    r = client.get("/login")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store"
    assert "httponly" in r.headers["set-cookie"].lower()


def test_code_issue_limit_per_user(client):
    register(client)
    token = csrf(client, "/verify")
    for _ in range(12):
        r = client.post("/verify/resend", data={"csrf": token})
    assert "через час" in r.text
    assert len(codes) == 10


# ---------- приложение-аутентификатор (TOTP) ----------

import sqlite3  # noqa: E402
import time  # noqa: E402

import pyotp  # noqa: E402


def totp_code(secret, steps=0):
    """Код для интервала со сдвигом steps (каждый код можно использовать только один раз)."""
    return pyotp.TOTP(secret).at(time.time() + 30 * steps)


def enable_totp(client):
    r = client.post("/settings/totp/start", data={"current_password": PASSWORD, "csrf": csrf(client, "/settings")})
    assert r.url.path == "/settings/totp"
    assert "data:image/svg+xml" in r.text
    secret = re.search(r'<code class="secret">([A-Z2-7 ]+)</code>', r.text).group(1).replace(" ", "")
    r = client.post("/settings/totp/confirm", data={"code": totp_code(secret, -1), "csrf": csrf(client, "/settings/totp")})
    backup = re.findall(r"<code>([a-z2-9]{4}-[a-z2-9]{4})</code>", r.text)
    assert len(backup) == 10
    return secret, backup


def test_totp_enable_and_login(client):
    signed_up(client)
    secret, _ = enable_totp(client)
    assert notices[-1] == (EMAIL, "Подключено приложение-аутентификатор")
    logout(client)
    sent = len(codes)
    r = login(client)
    assert r.url.path == "/verify" and "Код из приложения" in r.text
    assert len(codes) == sent  # письмо с кодом не отправляется
    assert verify(client, "000000" if totp_code(secret) != "000000" else "111111").url.path == "/verify"
    r = verify(client, totp_code(secret))
    assert r.url.path == "/dashboard" and "пароль + приложение" in r.text


def test_totp_code_cannot_be_reused(client):
    signed_up(client)
    secret, _ = enable_totp(client)
    logout(client)
    login(client)
    code = totp_code(secret)
    verify(client, code)
    logout(client)
    login(client)
    assert verify(client, code).url.path == "/verify"  # тот же код второй раз не проходит
    assert verify(client, totp_code(secret, 1)).url.path == "/dashboard"


def test_totp_wrong_setup_code_does_not_enable(client):
    signed_up(client)
    client.post("/settings/totp/start", data={"current_password": PASSWORD, "csrf": csrf(client, "/settings")})
    r = client.post("/settings/totp/confirm", data={"code": "123456", "csrf": csrf(client, "/settings/totp")})
    assert "Код не подошёл" in r.text
    logout(client)
    login(client)
    assert codes[-1][2] == "login"  # по-прежнему код на почту


def test_backup_code_single_use(client):
    signed_up(client)
    _, backup = enable_totp(client)
    logout(client)
    login(client)
    r = verify(client, backup[0].upper())  # регистр и дефис не важны
    assert r.url.path == "/dashboard" and "Осталось кодов: 9" in r.text
    assert notices[-1] == (EMAIL, "Использован резервный код")
    logout(client)
    login(client)
    assert verify(client, backup[0]).url.path == "/verify"


def test_totp_bruteforce_lock(client):
    signed_up(client)
    secret, _ = enable_totp(client)
    logout(client)
    login(client)
    wrong = "000000" if totp_code(secret) != "000000" else "111111"
    for _ in range(5):
        verify(client, wrong)
    r = verify(client, totp_code(secret))
    assert r.url.path == "/verify" and "Слишком много" in r.text


def test_reset_password_still_requires_totp(client):
    signed_up(client)
    secret, _ = enable_totp(client)
    logout(client)
    client.post("/forgot", data={"email": EMAIL, "csrf": csrf(client, "/forgot")})
    verify(client)
    r = client.post("/reset", data={"password": NEW_PASSWORD, "password2": NEW_PASSWORD, "csrf": csrf(client, "/reset")})
    assert r.url.path == "/verify" and "Код из приложения" in r.text  # почты недостаточно
    assert client.get("/dashboard").url.path == "/login"
    assert verify(client, totp_code(secret)).url.path == "/dashboard"


def test_totp_disable_requires_password_and_code(client):
    signed_up(client)
    secret, _ = enable_totp(client)
    r = client.post("/settings/totp/disable", data={
        "current_password": PASSWORD, "code": "000000" if totp_code(secret) != "000000" else "111111",
        "csrf": csrf(client, "/settings")})
    assert r.status_code == 400
    r = client.post("/settings/totp/disable", data={
        "current_password": PASSWORD, "code": totp_code(secret), "csrf": csrf(client, "/settings")})
    assert "отключено" in r.text
    assert notices[-1] == (EMAIL, "Приложение-аутентификатор отключено")
    logout(client)
    login(client)
    assert codes[-1][2] == "login"


def test_totp_secret_encrypted_in_db(client):
    signed_up(client)
    secret, _ = enable_totp(client)
    row = sqlite3.connect("data/test.db").execute("SELECT totp_secret FROM users").fetchone()
    assert row[0] and secret not in row[0]
    backup_rows = sqlite3.connect("data/test.db").execute("SELECT code_hash FROM backup_codes").fetchall()
    assert len(backup_rows) == 10 and all("-" not in r[0] for r in backup_rows)


def test_migration_adds_totp_columns(tmp_path, monkeypatch):
    import asyncio
    from auth_core import db as db_module
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, username TEXT,
                   password_hash TEXT, email_verified INTEGER, created_at INTEGER, last_login_at INTEGER)""")
    old.execute("INSERT INTO users VALUES (1, 'old@example.com', 'Old', 'x', 1, 0, NULL)")
    old.commit()
    old.close()
    monkeypatch.setattr(db_module.settings, "database_path", str(path))
    asyncio.run(db_module.init_db())
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(users)")}
    assert {"totp_secret", "totp_enabled", "totp_last_step", "password_changed_at"} <= cols
    assert sqlite3.connect(path).execute("SELECT email FROM users").fetchone()[0] == "old@example.com"


# ---------- имя пользователя (логин в мессенджере) ----------

@pytest.mark.parametrize("bad", ["ab", "имя_кириллицей", "аlice", "with space", "x" * 33])
def test_bad_usernames_rejected(client, bad):
    r = register(client, name=bad)
    assert r.status_code == 400 and not codes


def test_username_must_be_unique(client):
    signed_up(client)
    logout(client)
    r = register(client, email="other@example.com", name="KIRILL")  # регистр не важен
    assert r.status_code == 400 and "занято" in r.text


def test_for_log_escapes_newlines():
    from auth_core.security import for_log
    assert for_log("a@b.c\r\nINFO: вход выполнен\x1b[0m") == "a@b.c\\r\\nINFO: вход выполнен\\x1b[0m"
