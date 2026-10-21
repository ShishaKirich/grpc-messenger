-- Схема базы данных. Выполняется при каждом старте, поэтому всё через IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    username       TEXT    NOT NULL,
    password_hash  TEXT    NOT NULL,
    email_verified INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    last_login_at  INTEGER,
    password_changed_at INTEGER,
    totp_secret    TEXT,                       -- секрет приложения-аутентификатора, зашифрован
    totp_enabled   INTEGER NOT NULL DEFAULT 0,
    totp_last_step INTEGER                     -- номер последнего принятого 30-секундного интервала
);

-- Резервные коды на случай потери телефона. Храним HMAC, каждый код одноразовый.
-- Имя пользователя — это и логин в мессенджере, поэтому оно уникально (без учёта регистра).
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS backup_codes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT    NOT NULL,
    used_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_backup_codes_user ON backup_codes(user_id);

-- Одноразовые коды. Храним не сам код, а его HMAC-хеш.
-- purpose: verify_email | login | reset | change_password | change_email
-- payload: данные, которые применятся после ввода кода (хеш нового пароля или новый email).
CREATE TABLE IF NOT EXISTS otp_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose    TEXT    NOT NULL,
    code_hash  TEXT    NOT NULL,
    payload    TEXT,
    ip         TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_otp_user_purpose ON otp_codes(user_id, purpose, id);
CREATE INDEX IF NOT EXISTS idx_otp_ip ON otp_codes(ip, created_at);

-- Сеансы входа. В cookie лежит случайный токен, в базе только его SHA-256,
-- поэтому утечка базы не даёт войти чужими сеансами.
CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash   TEXT    NOT NULL UNIQUE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip           TEXT,
    user_agent   TEXT,
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- Устройства пользователя. Устройство узнаём по долгоживущей cookie со случайным токеном.
-- trusted_until: до какого момента на этом устройстве не спрашивать код (NULL — не доверять).
CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash    TEXT    NOT NULL,
    ip            TEXT,
    user_agent    TEXT,
    first_seen_at INTEGER NOT NULL,
    last_seen_at  INTEGER NOT NULL,
    trusted_until INTEGER,
    UNIQUE (user_id, token_hash)
);

-- Журнал попыток входа: блокировка подбора пароля и история в личном кабинете.
-- method: password_fail | totp_fail | otp | totp | backup_code | trusted_device | reset
CREATE TABLE IF NOT EXISTS login_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT    NOT NULL COLLATE NOCASE,
    ip         TEXT,
    user_agent TEXT,
    success    INTEGER NOT NULL,
    method     TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_events_email ON login_events(email, created_at);
