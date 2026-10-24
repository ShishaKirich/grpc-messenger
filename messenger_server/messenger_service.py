"""Сервис сообщений и контактов.

Каждый метод начинается с authenticate(): кто вызывает, сервер узнаёт только из токена.
Все проверки прав (дружба, блокировки, чья это переписка) делаются здесь, на сервере.
Клиенту доверять нельзя: его можно заменить своим скриптом.

Сервер не может прочитать сообщения: в базу попадает шифротекст, ключи есть только
у устройств собеседников (см. docs/CRYPTO.md).
"""
import asyncio
import hashlib
import time
from collections import defaultdict, deque

import aiosqlite
import grpc
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from auth_core.config import settings
from auth_core.db import fetch_all, fetch_one, opened
from proto import messenger_pb2 as pb
from proto import messenger_pb2_grpc as pb_grpc

from .guard import authenticate, bearer_token, find_session
from .hub import Hub

HEADER_MAX = 4096
HISTORY_MAX = 200
SESSION_RECHECK_SECONDS = 30   # как часто открытый поток проверяет, не отозван ли сеанс
STATE_BY_NAME = {"friend": pb.FRIEND, "incoming": pb.INCOMING, "outgoing": pb.OUTGOING}


def contact_event(username: str, state: int, key_id: int = 0) -> pb.Event:
    return pb.Event(contact=pb.Contact(username=username, state=state, key_id=key_id))


def to_envelope(row: aiosqlite.Row) -> pb.Envelope:
    return pb.Envelope(id=row["id"], sender=row["sender"], recipient=row["recipient"], kind=row["kind"],
                       header=row["header"], ciphertext=row["ciphertext"], sent_at=row["sent_at"])


MESSAGE_SELECT = """
    SELECT m.id, m.kind, m.header, m.ciphertext, m.sent_at, s.username AS sender, r.username AS recipient
    FROM messages m JOIN users s ON s.id = m.sender_id JOIN users r ON r.id = m.recipient_id
"""


class MessengerService(pb_grpc.MessengerServicer):

    def __init__(self, hub: Hub | None = None) -> None:
        self.hub = hub or Hub()
        self._sent: dict[int, deque] = defaultdict(deque)   # время последних отправок, для лимита

    # ---------- поток событий ----------

    async def Subscribe(self, request: pb.Empty, context: grpc.aio.ServicerContext):
        async with opened() as db:
            me = await authenticate(db, context)
            queue = self.hub.subscribe(me["id"])
            # Недоставленные сообщения секретных чатов: пока клиент был не в сети, они ждали на сервере
            pending = await fetch_all(db, MESSAGE_SELECT + " WHERE m.recipient_id = ? AND m.kind = ? ORDER BY m.id",
                                      (me["id"], pb.SECRET))
        token = bearer_token(context)
        # Клиент отключился — будим цикл ниже пустым событием, чтобы сразу освободить очередь
        context.add_done_callback(lambda _: queue.put_nowait(None))
        try:
            for row in pending:
                yield pb.Event(message=to_envelope(row))
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SESSION_RECHECK_SECONDS)
                    if event is None:
                        return
                    yield event
                except asyncio.TimeoutError:
                    # Сеанс могли завершить на сайте («Выйти везде») — тогда закрываем поток
                    async with opened() as db:
                        if await find_session(db, token) is None:
                            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Сеанс завершён. Войдите заново.")
        finally:
            self.hub.unsubscribe(me["id"], queue)

    # ---------- ключи ----------

    async def PublishKeys(self, request: pb.KeyBundle, context: grpc.aio.ServicerContext) -> pb.Empty:
        keys = (request.identity_dh, request.identity_sign, request.signed_prekey)
        if any(len(k) != 32 for k in keys) or len(request.prekey_signature) != 64:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Неверный формат ключей.")
        try:  # prekey должен быть подписан ключом устройства, иначе его мог подменить кто угодно
            Ed25519PublicKey.from_public_bytes(request.identity_sign).verify(request.prekey_signature,
                                                                             request.signed_prekey)
        except InvalidSignature:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Подпись ключа не сходится.")
        key_id = int.from_bytes(hashlib.sha256(request.identity_dh + request.identity_sign).digest()[:7], "big")

        async with opened() as db:
            me = await authenticate(db, context)
            old = await fetch_one(db, "SELECT key_id FROM device_keys WHERE user_id = ?", (me["id"],))
            await db.execute(
                """INSERT INTO device_keys (user_id, key_id, identity_dh, identity_sign, signed_prekey,
                                            prekey_signature, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (user_id) DO UPDATE SET key_id = excluded.key_id, identity_dh = excluded.identity_dh,
                       identity_sign = excluded.identity_sign, signed_prekey = excluded.signed_prekey,
                       prekey_signature = excluded.prekey_signature, updated_at = excluded.updated_at""",
                (me["id"], key_id, *keys, request.prekey_signature, int(time.time())),
            )
            if old and old["key_id"] != key_id:
                # Новое устройство: друзья увидят предупреждение и смогут сверить код безопасности
                for friend in await self._friends(db, me["id"]):
                    self.hub.publish(friend["id"], contact_event(me["username"], pb.KEY_CHANGED, key_id))
        return pb.Empty()

    async def GetKeys(self, request: pb.UserRef, context: grpc.aio.ServicerContext) -> pb.KeyBundle:
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.username)
            if peer["id"] != me["id"] and await self._state(db, me["id"], peer["id"]) != "friend":
                await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Ключи доступны только друзьям.")
            row = await fetch_one(db, "SELECT * FROM device_keys WHERE user_id = ?", (peer["id"],))
        if row is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Собеседник ещё не входил в мессенджер.")
        return pb.KeyBundle(username=peer["username"], identity_dh=row["identity_dh"],
                            identity_sign=row["identity_sign"], signed_prekey=row["signed_prekey"],
                            prekey_signature=row["prekey_signature"], key_id=row["key_id"])

    # ---------- контакты ----------

    async def ListContacts(self, request: pb.Empty, context: grpc.aio.ServicerContext) -> pb.ContactList:
        async with opened() as db:
            me = await authenticate(db, context)
            rows = await fetch_all(db,
                """SELECT u.username, c.state, COALESCE(k.key_id, 0) AS key_id
                   FROM contacts c JOIN users u ON u.id = c.peer_id
                   LEFT JOIN device_keys k ON k.user_id = c.peer_id
                   WHERE c.user_id = ? ORDER BY u.username COLLATE NOCASE""", (me["id"],))
            blocked = await fetch_all(db,
                """SELECT u.username FROM blocks b JOIN users u ON u.id = b.blocked_id
                   WHERE b.user_id = ? ORDER BY u.username COLLATE NOCASE""", (me["id"],))
        contacts = [pb.Contact(username=r["username"], state=STATE_BY_NAME[r["state"]], key_id=r["key_id"])
                    for r in rows]
        contacts += [pb.Contact(username=r["username"], state=pb.BLOCKED) for r in blocked]
        return pb.ContactList(contacts=contacts)

    async def SendFriendRequest(self, request: pb.UserRef, context: grpc.aio.ServicerContext) -> pb.Empty:
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.username)
            if peer["id"] == me["id"]:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Нельзя добавить в друзья самого себя.")
            if await self._blocked(db, me["id"], peer["id"]):
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Сначала разблокируйте пользователя.")
            state = await self._state(db, me["id"], peer["id"])
            if state == "friend":
                await context.abort(grpc.StatusCode.ALREADY_EXISTS, "Вы уже друзья.")
            if state == "incoming":  # он уже звал нас в друзья — встречная заявка значит «да»
                await self._make_friends(db, me, peer)
                return pb.Empty()

            now = int(time.time())
            await db.execute("INSERT OR REPLACE INTO contacts VALUES (?, ?, 'outgoing', ?)", (me["id"], peer["id"], now))
            # Если он нас заблокировал, заявка до него не доходит, но и мы об этом не узнаём
            if not await self._blocked(db, peer["id"], me["id"]):
                await db.execute("INSERT OR REPLACE INTO contacts VALUES (?, ?, 'incoming', ?)",
                                 (peer["id"], me["id"], now))
                self.hub.publish(peer["id"], contact_event(me["username"], pb.INCOMING))
        self.hub.publish(me["id"], contact_event(peer["username"], pb.OUTGOING))
        return pb.Empty()

    async def AnswerFriendRequest(self, request: pb.FriendAnswer, context: grpc.aio.ServicerContext) -> pb.Empty:
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.username)
            # Принять можно только заявку, которая пришла именно нам
            if await self._state(db, me["id"], peer["id"]) != "incoming":
                await context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Заявки от этого пользователя нет.")
            if request.accept:
                await self._make_friends(db, me, peer)
            else:
                await self._unlink(db, me, peer)
        return pb.Empty()

    async def RemoveFriend(self, request: pb.UserRef, context: grpc.aio.ServicerContext) -> pb.Empty:
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.username)
            await self._unlink(db, me, peer)
        return pb.Empty()

    async def Block(self, request: pb.UserRef, context: grpc.aio.ServicerContext) -> pb.Empty:
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.username)
            if peer["id"] == me["id"]:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Нельзя заблокировать самого себя.")
            await self._unlink(db, me, peer)
            await db.execute("INSERT OR IGNORE INTO blocks VALUES (?, ?, ?)", (me["id"], peer["id"], int(time.time())))
        self.hub.publish(me["id"], contact_event(peer["username"], pb.BLOCKED))
        return pb.Empty()

    async def Unblock(self, request: pb.UserRef, context: grpc.aio.ServicerContext) -> pb.Empty:
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.username)
            await db.execute("DELETE FROM blocks WHERE user_id = ? AND blocked_id = ?", (me["id"], peer["id"]))
        self.hub.publish(me["id"], contact_event(peer["username"], pb.NONE))
        return pb.Empty()

    # ---------- сообщения ----------

    async def SendMessage(self, request: pb.Envelope, context: grpc.aio.ServicerContext) -> pb.SendReply:
        if request.kind not in (pb.REGULAR, pb.SECRET):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Неизвестный тип чата.")
        if not request.ciphertext or len(request.ciphertext) > settings.message_max_bytes \
                or len(request.header) > HEADER_MAX:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Сообщение пустое или слишком большое.")

        async with opened() as db:
            me = await authenticate(db, context)
            if not self._within_rate_limit(me["id"]):
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "Слишком много сообщений. Подождите минуту.")
            peer = await self._user_or_abort(db, context, request.recipient)
            # Писать можно только друзьям, и только если никто из двоих не заблокировал другого
            if await self._state(db, me["id"], peer["id"]) != "friend" \
                    or await self._blocked(db, peer["id"], me["id"]) or await self._blocked(db, me["id"], peer["id"]):
                await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Писать можно только друзьям.")

            now = int(time.time())
            cur = await db.execute(
                "INSERT INTO messages (sender_id, recipient_id, kind, header, ciphertext, sent_at) VALUES (?, ?, ?, ?, ?, ?)",
                (me["id"], peer["id"], request.kind, request.header, request.ciphertext, now),
            )
            message_id = cur.lastrowid

        # sender и время ставит сервер — то, что прислал клиент в этих полях, игнорируется
        envelope = pb.Envelope(id=message_id, sender=me["username"], recipient=peer["username"], kind=request.kind,
                               header=request.header, ciphertext=request.ciphertext, sent_at=now)
        self.hub.publish(peer["id"], pb.Event(message=envelope))
        if request.kind == pb.REGULAR:
            self.hub.publish(me["id"], pb.Event(message=envelope))  # другие окна этого же пользователя
        return pb.SendReply(id=message_id, sent_at=now)

    async def History(self, request: pb.HistoryRequest, context: grpc.aio.ServicerContext) -> pb.HistoryReply:
        limit = min(max(request.limit or 50, 1), HISTORY_MAX)
        before = request.before_id or 2 ** 62
        async with opened() as db:
            me = await authenticate(db, context)
            peer = await self._user_or_abort(db, context, request.peer)
            # Только переписка вызывающего с этим собеседником и только обычные чаты:
            # чужие диалоги через History не получить, даже подставив любые имена
            rows = await fetch_all(db, MESSAGE_SELECT + """
                WHERE m.kind = ? AND m.id < ?
                  AND ((m.sender_id = ? AND m.recipient_id = ?) OR (m.sender_id = ? AND m.recipient_id = ?))
                ORDER BY m.id DESC LIMIT ?""",
                (pb.REGULAR, before, me["id"], peer["id"], peer["id"], me["id"], limit))
        return pb.HistoryReply(messages=[to_envelope(r) for r in reversed(rows)])

    async def Acknowledge(self, request: pb.AckRequest, context: grpc.aio.ServicerContext) -> pb.Empty:
        ids = list(request.ids)[:500]
        async with opened() as db:
            me = await authenticate(db, context)
            for message_id in ids:
                # recipient_id = me: удалить можно только сообщения, адресованные себе
                await db.execute("DELETE FROM messages WHERE id = ? AND recipient_id = ? AND kind = ?",
                                 (message_id, me["id"], pb.SECRET))
        return pb.Empty()

    # ---------- вспомогательное ----------

    @staticmethod
    async def _user_or_abort(db: aiosqlite.Connection, context, username: str) -> aiosqlite.Row:
        row = None
        if 0 < len(username) <= 32:
            row = await fetch_one(db, "SELECT id, username FROM users WHERE username = ? AND email_verified = 1",
                                  (username,))
        if row is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Пользователь не найден.")
        return row

    @staticmethod
    async def _state(db: aiosqlite.Connection, user_id: int, peer_id: int) -> str | None:
        row = await fetch_one(db, "SELECT state FROM contacts WHERE user_id = ? AND peer_id = ?", (user_id, peer_id))
        return row["state"] if row else None

    @staticmethod
    async def _blocked(db: aiosqlite.Connection, user_id: int, blocked_id: int) -> bool:
        return await fetch_one(db, "SELECT 1 FROM blocks WHERE user_id = ? AND blocked_id = ?",
                               (user_id, blocked_id)) is not None

    @staticmethod
    async def _friends(db: aiosqlite.Connection, user_id: int) -> list[aiosqlite.Row]:
        return await fetch_all(db, "SELECT peer_id AS id FROM contacts WHERE user_id = ? AND state = 'friend'",
                               (user_id,))

    async def _make_friends(self, db: aiosqlite.Connection, me: aiosqlite.Row, peer: aiosqlite.Row) -> None:
        now = int(time.time())
        await db.execute("INSERT OR REPLACE INTO contacts VALUES (?, ?, 'friend', ?)", (me["id"], peer["id"], now))
        await db.execute("INSERT OR REPLACE INTO contacts VALUES (?, ?, 'friend', ?)", (peer["id"], me["id"], now))
        self.hub.publish(me["id"], contact_event(peer["username"], pb.FRIEND))
        self.hub.publish(peer["id"], contact_event(me["username"], pb.FRIEND))

    async def _unlink(self, db: aiosqlite.Connection, me: aiosqlite.Row, peer: aiosqlite.Row) -> None:
        await db.execute("DELETE FROM contacts WHERE (user_id = ? AND peer_id = ?) OR (user_id = ? AND peer_id = ?)",
                         (me["id"], peer["id"], peer["id"], me["id"]))
        self.hub.publish(me["id"], contact_event(peer["username"], pb.NONE))
        self.hub.publish(peer["id"], contact_event(me["username"], pb.NONE))

    def _within_rate_limit(self, user_id: int) -> bool:
        """Не больше messages_per_minute сообщений за последние 60 секунд."""
        now = time.monotonic()
        sent = self._sent[user_id]
        while sent and now - sent[0] > 60:
            sent.popleft()
        if len(sent) >= settings.messages_per_minute:
            return False
        sent.append(now)
        return True
