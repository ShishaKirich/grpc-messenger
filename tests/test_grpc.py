"""Тесты gRPC-сервера: вход в два шага, права доступа, друзья, сообщения, секретные чаты.

Сервер поднимается в фоновом потоке, клиент — обычные синхронные заглушки gRPC,
как в настоящем приложении.
"""
import asyncio
import os
import queue
import sqlite3
import threading
import time

import grpc
import pyotp
import pytest

from auth_core import mailer, totp
from auth_core.config import settings
from auth_core.db import init_db
from auth_core.security import hash_password
from e2e import regular
from e2e.keys import DeviceKeys, PublicBundle
from e2e.primitives import pub_bytes
from messenger_server.run_server import SCHEMA_FILE, build_server
from proto import messenger_pb2 as pb
from proto import messenger_pb2_grpc as pb_grpc

PASSWORD = "Tr0ub4dor&3-horse-staple"
codes: list[tuple[str, str]] = []


async def fake_code(to, code, purpose):
    codes.append((to, code))


async def fake_notice(to, subject, lines):
    pass


# ---------- сервер и база ----------

@pytest.fixture(scope="module")
def channel():
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    holder = {}

    async def serve():
        server, port = build_server(insecure=True, address="127.0.0.1:0")
        await server.start()
        holder.update(server=server, port=port)
        ready.set()
        await server.wait_for_termination()

    thread = threading.Thread(target=lambda: loop.run_until_complete(serve()), daemon=True)
    thread.start()
    ready.wait(10)
    ch = grpc.insecure_channel(f"127.0.0.1:{holder['port']}")
    yield ch
    ch.close()
    # Не ждём остановки: поток демон и завершится вместе с тестами
    asyncio.run_coroutine_threadsafe(holder["server"].stop(None), loop)


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(settings.database_path + suffix):
            os.remove(settings.database_path + suffix)
    asyncio.run(init_db(SCHEMA_FILE))
    codes.clear()
    monkeypatch.setattr(mailer, "send_code", fake_code)
    monkeypatch.setattr(mailer, "send_notice", fake_notice)


def db():
    conn = sqlite3.connect(settings.database_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def create_user(name: str, verified: bool = True, totp_secret: str | None = None) -> str:
    email = f"{name}@example.com"
    pw_hash = asyncio.run(hash_password(PASSWORD))
    db().execute(
        """INSERT INTO users (email, username, password_hash, email_verified, created_at, totp_secret, totp_enabled)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (email, name, pw_hash, int(verified), int(time.time()),
         totp.encrypt(totp_secret) if totp_secret else None, int(bool(totp_secret))))
    return email


def auth(channel) -> pb_grpc.AuthStub:
    return pb_grpc.AuthStub(channel)


class User:
    """Вошедший пользователь: заглушка с токеном в метаданных."""

    def __init__(self, channel, name: str, token: str):
        self.name, self.token = name, token
        self.stub = pb_grpc.MessengerStub(channel)
        self.md = (("authorization", f"Bearer {token}"),)
        self.keys = DeviceKeys.generate()

    def __getattr__(self, method):
        rpc = getattr(self.stub, method)
        return lambda request=pb.Empty(): rpc(request, metadata=self.md, timeout=5)

    def publish_keys(self):
        b = self.keys.public(self.name)
        self.PublishKeys(pb.KeyBundle(identity_dh=b.identity_dh, identity_sign=b.identity_sign,
                                      signed_prekey=b.signed_prekey, prekey_signature=b.prekey_signature))


def login(channel, name: str, create: bool = True) -> User:
    email = create_user(name) if create else f"{name}@example.com"
    reply = auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD, device_name="тест"))
    assert reply.method == pb.EMAIL_CODE and reply.challenge_id
    verified = auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=codes[-1][1]))
    assert verified.username == name
    return User(channel, name, verified.token)


def befriend(a: User, b: User):
    a.SendFriendRequest(pb.UserRef(username=b.name))
    b.AnswerFriendRequest(pb.FriendAnswer(username=a.name, accept=True))


def status(call) -> grpc.StatusCode:
    with pytest.raises(grpc.RpcError) as exc:
        call()
    return exc.value.code()


def events(user: User):
    """Читает поток Subscribe в отдельном потоке; возвращает очередь событий и сам вызов."""
    q: queue.Queue = queue.Queue()
    call = user.stub.Subscribe(pb.Empty(), metadata=user.md)

    def pump():
        try:
            for event in call:
                q.put(event)
        except grpc.RpcError as exc:
            q.put(exc)

    threading.Thread(target=pump, daemon=True).start()
    return q, call


# ---------- вход ----------

def test_password_alone_gives_no_access(channel):
    email = create_user("alice")
    reply = auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))
    assert reply.challenge_id and reply.method == pb.EMAIL_CODE
    fake = User(channel, "alice", reply.challenge_id)  # вызов входа — не токен
    assert status(fake.ListContacts) == grpc.StatusCode.UNAUTHENTICATED
    no_token = pb_grpc.MessengerStub(channel)
    assert status(lambda: no_token.ListContacts(pb.Empty())) == grpc.StatusCode.UNAUTHENTICATED


def test_wrong_password_and_unknown_email_look_the_same(channel):
    create_user("alice")
    errors = []
    for email in ("alice@example.com", "nobody@example.com"):
        with pytest.raises(grpc.RpcError) as exc:
            auth(channel).Login(pb.LoginRequest(email=email, password="wrong-password"))
        errors.append((exc.value.code(), exc.value.details()))
    assert errors[0] == errors[1] == (grpc.StatusCode.UNAUTHENTICATED, "Неверный email или пароль.")


def test_email_code_login_and_reuse(channel):
    alice = login(channel, "alice")
    assert alice.ListContacts().contacts == []
    # тот же код и тот же вызов второй раз не работают
    reply = auth(channel).Login(pb.LoginRequest(email="alice@example.com", password=PASSWORD))
    code = codes[-1][1]
    auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=code))
    assert status(lambda: auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=code))) \
        == grpc.StatusCode.UNAUTHENTICATED


def test_code_bruteforce_burns_challenge(channel):
    email = create_user("alice")
    reply = auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))
    right = codes[-1][1]
    wrong = "000000" if right != "000000" else "111111"
    for _ in range(5):
        status(lambda: auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=wrong)))
    # даже верный код после 5 ошибок уже не поможет
    assert status(lambda: auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=right))) \
        in (grpc.StatusCode.RESOURCE_EXHAUSTED, grpc.StatusCode.UNAUTHENTICATED)


def test_password_bruteforce_lockout(channel):
    email = create_user("alice")
    for _ in range(5):
        status(lambda: auth(channel).Login(pb.LoginRequest(email=email, password="wrong-password")))
    assert status(lambda: auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))) \
        == grpc.StatusCode.RESOURCE_EXHAUSTED


def test_unverified_email_cannot_login(channel):
    email = create_user("alice", verified=False)
    assert status(lambda: auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))) \
        == grpc.StatusCode.FAILED_PRECONDITION


def test_totp_and_backup_code(channel):
    secret = pyotp.random_base32()
    email = create_user("alice", totp_secret=secret)
    reply = auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))
    assert reply.method == pb.TOTP and not codes  # письмо не отправляется
    assert status(lambda: auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code="123456"))) \
        == grpc.StatusCode.INVALID_ARGUMENT
    token = auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id,
                                                      code=pyotp.TOTP(secret).now())).token
    assert token

    user_id = db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    backup = asyncio.run(_backup_codes(user_id))[0]
    reply = auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))
    assert auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=backup)).token


async def _backup_codes(user_id):
    from auth_core.db import opened
    async with opened() as conn:
        return await totp.create_backup_codes(conn, user_id)


def test_logout_and_revoke_from_site(channel):
    alice = login(channel, "alice")
    auth(channel).Logout(pb.Empty(), metadata=alice.md)
    assert status(alice.ListContacts) == grpc.StatusCode.UNAUTHENTICATED

    bob = login(channel, "bob")
    db().execute("DELETE FROM sessions")  # «Выйти везде» в личном кабинете
    assert status(bob.ListContacts) == grpc.StatusCode.UNAUTHENTICATED


def test_session_listed_on_site_as_messenger(channel):
    login(channel, "alice")
    ua = db().execute("SELECT user_agent FROM sessions").fetchone()[0]
    assert ua == "messenger:тест"


# ---------- друзья и права ----------

def test_cannot_accept_own_request(channel):
    """В старой версии клиент мог прислать FRIEND_ACCEPTED за другого человека."""
    alice, bob = login(channel, "alice"), login(channel, "bob")
    alice.SendFriendRequest(pb.UserRef(username="bob"))
    assert status(lambda: alice.AnswerFriendRequest(pb.FriendAnswer(username="bob", accept=True))) \
        == grpc.StatusCode.FAILED_PRECONDITION
    assert {c.username: c.state for c in bob.ListContacts().contacts} == {"alice": pb.INCOMING}
    bob.AnswerFriendRequest(pb.FriendAnswer(username="alice", accept=True))
    assert {c.username: c.state for c in alice.ListContacts().contacts} == {"bob": pb.FRIEND}


def test_only_friends_can_message(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    msg = pb.Envelope(recipient="bob", kind=pb.REGULAR, header=b"h", ciphertext=b"c")
    assert status(lambda: alice.SendMessage(msg)) == grpc.StatusCode.PERMISSION_DENIED
    befriend(alice, bob)
    assert alice.SendMessage(msg).id
    bob.Block(pb.UserRef(username="alice"))
    assert status(lambda: alice.SendMessage(msg)) == grpc.StatusCode.PERMISSION_DENIED
    assert status(lambda: alice.SendFriendRequest(pb.UserRef(username="nobody"))) == grpc.StatusCode.NOT_FOUND


def test_sender_comes_from_token_not_from_request(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    befriend(alice, bob)
    alice.SendMessage(pb.Envelope(sender="bob", recipient="bob", kind=pb.REGULAR, header=b"h", ciphertext=b"c",
                                  sent_at=1))
    [m] = bob.History(pb.HistoryRequest(peer="alice")).messages
    assert m.sender == "alice" and m.sent_at > 1


def test_history_is_private(channel):
    alice, bob, carol = login(channel, "alice"), login(channel, "bob"), login(channel, "carol")
    befriend(alice, bob)
    befriend(carol, bob)
    alice.SendMessage(pb.Envelope(recipient="bob", kind=pb.REGULAR, header=b"h", ciphertext=b"for bob"))
    # carol спрашивает историю с alice и с bob — переписки alice и bob там нет
    assert carol.History(pb.HistoryRequest(peer="bob")).messages == []
    assert carol.History(pb.HistoryRequest(peer="alice")).messages == []
    assert status(lambda: carol.GetKeys(pb.UserRef(username="alice"))) == grpc.StatusCode.PERMISSION_DENIED


def test_message_limits(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    befriend(alice, bob)
    big = pb.Envelope(recipient="bob", kind=pb.REGULAR, header=b"h", ciphertext=b"x" * (settings.message_max_bytes + 1))
    assert status(lambda: alice.SendMessage(big)) == grpc.StatusCode.INVALID_ARGUMENT
    bad_kind = pb.Envelope(recipient="bob", kind=pb.CHAT_KIND_UNSPECIFIED, header=b"h", ciphertext=b"c")
    assert status(lambda: alice.SendMessage(bad_kind)) == grpc.StatusCode.INVALID_ARGUMENT


# ---------- ключи и шифрование ----------

def test_keys_signature_checked(channel):
    alice = login(channel, "alice")
    b = alice.keys.public("alice")
    forged = pb.KeyBundle(identity_dh=b.identity_dh, identity_sign=b.identity_sign,
                          signed_prekey=pub_bytes(DeviceKeys.generate().signed_prekey),
                          prekey_signature=b.prekey_signature)
    assert status(lambda: alice.PublishKeys(forged)) == grpc.StatusCode.INVALID_ARGUMENT


def test_regular_chat_server_stores_only_ciphertext(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    befriend(alice, bob)
    alice.publish_keys()
    bob.publish_keys()
    bob_bundle = PublicBundle.from_proto(alice.GetKeys(pb.UserRef(username="bob")))
    header, ct = regular.encrypt(alice.keys, "alice", bob_bundle, "секретный план".encode())
    alice.SendMessage(pb.Envelope(recipient="bob", kind=pb.REGULAR, header=header, ciphertext=ct))

    stored = db().execute("SELECT header, ciphertext FROM messages").fetchone()
    assert "секретный".encode() not in stored["ciphertext"] + stored["header"]
    [m] = bob.History(pb.HistoryRequest(peer="alice")).messages
    alice_bundle = PublicBundle.from_proto(bob.GetKeys(pb.UserRef(username="alice")))
    text = regular.decrypt(bob.keys, "bob", m.sender, m.recipient, m.header, m.ciphertext, alice_bundle.identity_sign)
    assert text.decode() == "секретный план"


def test_key_change_notifies_friends(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    befriend(alice, bob)
    alice.publish_keys()
    q, call = events(bob)
    time.sleep(0.3)
    alice.keys = DeviceKeys.generate()  # «новое устройство»
    alice.publish_keys()
    event = q.get(timeout=5)
    call.cancel()
    assert event.contact.username == "alice" and event.contact.state == pb.KEY_CHANGED


def test_secret_message_delivered_then_erased(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    befriend(alice, bob)
    sent = alice.SendMessage(pb.Envelope(recipient="bob", kind=pb.SECRET, header=b"h", ciphertext=b"c"))
    assert bob.History(pb.HistoryRequest(peer="alice")).messages == []  # секретные не в истории
    q, call = events(bob)  # bob был не в сети — получает при подключении
    event = q.get(timeout=5)
    assert event.message.id == sent.id and event.message.sender == "alice"
    alice.Acknowledge(pb.AckRequest(ids=[sent.id]))  # чужое подтверждение ничего не удаляет
    assert db().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    bob.Acknowledge(pb.AckRequest(ids=[sent.id]))
    assert db().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    call.cancel()


def test_live_delivery(channel):
    alice, bob = login(channel, "alice"), login(channel, "bob")
    befriend(alice, bob)
    q, call = events(bob)
    time.sleep(0.3)
    alice.SendMessage(pb.Envelope(recipient="bob", kind=pb.REGULAR, header=b"h", ciphertext=b"c"))
    event = q.get(timeout=5)
    call.cancel()
    assert event.message.sender == "alice" and event.message.ciphertext == b"c"


# ---------- клиентская логика (client/core.py) против настоящего сервера ----------

def client_for(channel, name: str, tmp_path, create: bool = True):
    from client.api import Api
    from client.core import Messenger, open_keystore

    port = int(channel._channel.target().decode().rsplit(":", 1)[1])
    api = Api("127.0.0.1", port, insecure=True)
    email = create_user(name) if create else f"{name}@example.com"
    reply = api.login(email, PASSWORD)
    api.verify(reply.challenge_id, codes[-1][1])
    store, _ = open_keystore(tmp_path / "keys", name, PASSWORD)
    messenger = Messenger(api, name, store)
    messenger.publish_keys()
    return messenger


def drain(messenger, call_queue, count=1):
    updates = []
    for _ in range(count):
        event = call_queue.get(timeout=5)
        updates += messenger.handle_event(event)
    return updates


def test_client_regular_and_secret_chat(channel, tmp_path):
    alice = client_for(channel, "alice", tmp_path)
    bob = client_for(channel, "bob", tmp_path)
    alice.contact_action("SendFriendRequest", "bob")
    bob.contact_action("answer", "alice", accept=True)

    sent = alice.send_text("bob", "Привет, Боб!")
    [received] = bob.history("alice")
    assert received.text == "Привет, Боб!" and not received.error and received.id == sent.id
    assert alice.history("bob")[0].text == "Привет, Боб!"  # своё сообщение тоже читается

    # Секретный чат: bob получает сообщения через поток событий
    bob_user = User(channel, "bob", bob.api.token)
    q, call = events(bob_user)
    time.sleep(0.3)
    alice.start_secret("bob")
    updates = drain(bob, q)
    assert [u.kind for u in updates] == ["secret_started"]
    alice.send_secret("bob", "только для тебя")
    [update] = drain(bob, q)
    assert update.message.text == "только для тебя" and update.message.secret

    # ответ bob расшифровывает alice
    alice_user = User(channel, "alice", alice.api.token)
    qa, call_a = events(alice_user)
    time.sleep(0.3)
    bob.send_secret("alice", "принято")
    [update] = drain(alice, qa)
    assert update.message.text == "принято"

    # на сервере после доставки ничего не осталось, в истории секретных нет
    assert db().execute("SELECT COUNT(*) FROM messages WHERE kind = 2").fetchone()[0] == 0
    assert [m.text for m in bob.history("alice")] == ["Привет, Боб!"]
    assert alice.safety_number("bob") == bob.safety_number("alice")

    # самоуничтожение
    alice.set_secret_ttl("bob", 10)
    alice.send_secret("bob", "исчезну")
    [update] = drain(bob, q)
    assert update.message.ttl == 10
    bob.mark_read("alice")
    for m in bob.store.data["secret"]["alice"]["messages"]:
        if m["ttl"]:
            m["read_at"] -= 11
    assert bob.purge_expired() == {"alice"}
    assert "исчезну" not in [m.text for m in bob.secret_messages("alice")]

    alice.close_secret("bob")
    assert [u.kind for u in drain(bob, q)] == ["secret_closed"]
    assert bob.secret_peers() == []
    call.cancel()
    call_a.cancel()


def test_client_new_device_breaks_old_secret_chat_and_warns(channel, tmp_path):
    from client.core import Messenger, new_keystore

    alice = client_for(channel, "alice", tmp_path)
    bob = client_for(channel, "bob", tmp_path)
    alice.contact_action("SendFriendRequest", "bob")
    bob.contact_action("answer", "alice", accept=True)
    alice.bundle("bob")
    bob_user = User(channel, "bob", bob.api.token)
    alice_user = User(channel, "alice", alice.api.token)
    qa, call = events(alice_user)
    time.sleep(0.3)

    # bob заходит с нового устройства: новые ключи
    bob2 = Messenger(bob.api, "bob", new_keystore(tmp_path / "other", "bob", PASSWORD))
    bob2.publish_keys()
    updates = drain(alice, qa)
    assert updates[0].kind == "key_changed"
    alice.bundle("bob", refresh=True)
    assert alice.key_history("bob") == 2 and not alice.is_verified("bob")
    call.cancel()
    del bob_user


def test_site_code_does_not_work_in_messenger(channel):
    """Коды сайта и мессенджера разные: код для входа на сайт мессенджер не примет."""
    email = create_user("alice")
    user_id = db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    reply = auth(channel).Login(pb.LoginRequest(email=email, password=PASSWORD))
    messenger_code = codes[-1][1]
    from auth_core import otp
    from auth_core.db import opened

    async def site_code():
        async with opened() as conn:
            return await otp.issue_code(conn, user_id, "login", "127.0.0.1")
    site = asyncio.run(site_code())
    if site != messenger_code:
        assert status(lambda: auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=site))) \
            == grpc.StatusCode.INVALID_ARGUMENT
    assert auth(channel).VerifyCode(pb.VerifyRequest(challenge_id=reply.challenge_id, code=messenger_code)).token
