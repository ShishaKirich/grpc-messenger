-- Таблицы мессенджера. Пользователи, сеансы и коды — общие с сайтом (auth_core/schema.sql).

-- Незавершённые входы: пароль верный, ждём второй фактор.
-- В клиенте лежит случайный challenge_id, в базе только его SHA-256.
CREATE TABLE IF NOT EXISTS login_challenges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT    NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    method      TEXT    NOT NULL,             -- email | totp
    device_name TEXT    NOT NULL,
    ip          TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);

-- Связи между пользователями. Каждая связь хранится двумя строками: для каждой стороны своя.
-- state: friend | outgoing (я отправил заявку) | incoming (мне прислали заявку)
CREATE TABLE IF NOT EXISTS contacts (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    peer_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state      TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, peer_id)
);

CREATE TABLE IF NOT EXISTS blocks (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, blocked_id)
);

-- Открытые ключи устройства. Закрытые ключи на сервер не попадают никогда.
CREATE TABLE IF NOT EXISTS device_keys (
    user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    key_id           INTEGER NOT NULL,
    identity_dh      BLOB    NOT NULL,
    identity_sign    BLOB    NOT NULL,
    signed_prekey    BLOB    NOT NULL,
    prekey_signature BLOB    NOT NULL,
    updated_at       INTEGER NOT NULL
);

-- Сообщения. Сервер хранит только шифротекст: прочитать его без ключей устройства нельзя.
-- kind: 1 — обычный чат (хранится), 2 — секретный (удаляется после подтверждения доставки)
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         INTEGER NOT NULL,
    header       BLOB    NOT NULL,
    ciphertext   BLOB    NOT NULL,
    sent_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id, recipient_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_id, kind, id);
