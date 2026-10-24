"""Логика клиента без интерфейса: ключи, контакты, шифрование, секретные чаты.

Интерфейс (client/ui) только показывает то, что возвращают методы Messenger.
Всё шифрование происходит здесь, на устройстве: на сервер уходит только шифротекст.

Методы вызываются из фоновых потоков, поэтому состояние защищено блокировкой.
"""
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from e2e import ratchet, regular
from e2e.keys import DeviceKeys, PublicBundle, safety_number
from e2e.keystore import Keystore
from e2e.primitives import b64, pub_bytes
from proto import messenger_pb2 as pb

from .api import Api, ApiError

TEXT_MAX = 4000
SECRET_TTL_CHOICES = {0: "Выкл.", 10: "10 секунд", 60: "1 минута", 3600: "1 час", 86400: "1 день"}


@dataclass
class ChatMessage:
    id: int
    peer: str
    outgoing: bool
    text: str
    sent_at: int
    secret: bool = False
    ttl: int = 0            # секретный чат: через сколько секунд после прочтения сообщение исчезнет
    read_at: int = 0
    error: bool = False     # не удалось расшифровать или проверить подпись
    system: bool = False    # служебная строка: «секретный чат начат» и т. п.

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class Update:
    """Что изменилось после события с сервера — интерфейс решает, что перерисовать."""
    kind: str               # message | contacts | key_changed | secret_started | secret_closed
    peer: str = ""
    message: ChatMessage | None = None


def open_keystore(folder: Path, username: str, password: str) -> tuple[Keystore, bool]:
    """Открывает хранилище ключей или создаёт новое с новыми ключами. Возвращает (хранилище, создано ли)."""
    if Keystore.exists(folder, username):
        return Keystore.open(folder, username, password), False  # WrongPassword, если пароль другой
    return new_keystore(folder, username, password), True


def new_keystore(folder: Path, username: str, password: str) -> Keystore:
    data = {"keys": DeviceKeys.generate().to_dict(), "known": {}, "verified": {}, "secret": {}}
    return Keystore.create(folder, username, password, data)


class Messenger:
    def __init__(self, api: Api, username: str, store: Keystore):
        self.api, self.me, self.store = api, username, store
        self.lock = threading.RLock()
        self.keys = DeviceKeys.from_dict(store.data["keys"])
        self.contacts: dict[str, int] = {}
        self._bundles: dict[str, PublicBundle] = {}

    # ---------- ключи ----------

    def publish_keys(self) -> None:
        b = self.keys.public(self.me)
        self.api.call("PublishKeys", pb.KeyBundle(identity_dh=b.identity_dh, identity_sign=b.identity_sign,
                                                  signed_prekey=b.signed_prekey,
                                                  prekey_signature=b.prekey_signature))

    def bundle(self, peer: str, refresh: bool = False) -> PublicBundle:
        """Открытые ключи собеседника. Новые ключи запоминаем: по ним проверяем старые сообщения."""
        with self.lock:
            if not refresh and peer in self._bundles:
                return self._bundles[peer]
        fresh = PublicBundle.from_proto(self.api.call("GetKeys", pb.UserRef(username=peer)))
        with self.lock:
            known = self.store.data["known"].setdefault(peer, [])
            if not any(k["identity_dh"] == b64(fresh.identity_dh) for k in known):
                known.append(fresh.to_dict())
                if len(known) > 1:  # ключ сменился — прежняя проверка кода безопасности больше не действует
                    self.store.data["verified"].pop(peer, None)
                self.store.save()
            self._bundles[peer] = fresh
            return fresh

    def _sign_key(self, peer: str, identity_dh: bytes | None) -> bytes | None:
        if identity_dh is None:
            return None
        for k in self.store.data["known"].get(peer, []):
            if k["identity_dh"] == b64(identity_dh):
                return PublicBundle.from_dict(k).identity_sign
        return None

    def safety_number(self, peer: str) -> str:
        return safety_number(self.keys.public(self.me), self.bundle(peer))

    def is_verified(self, peer: str) -> bool:
        with self.lock:
            bundle = self._bundles.get(peer)
            return bool(bundle) and self.store.data["verified"].get(peer) == b64(bundle.identity_dh)

    def set_verified(self, peer: str) -> None:
        bundle = self.bundle(peer)
        with self.lock:
            self.store.data["verified"][peer] = b64(bundle.identity_dh)
            self.store.save()

    def key_history(self, peer: str) -> int:
        with self.lock:
            return len(self.store.data["known"].get(peer, []))

    # ---------- контакты ----------

    def refresh_contacts(self) -> dict[str, int]:
        reply = self.api.call("ListContacts")
        with self.lock:
            self.contacts = {c.username: c.state for c in reply.contacts}
            return dict(self.contacts)

    def contact_action(self, action: str, peer: str, accept: bool = True) -> None:
        if action == "answer":
            self.api.call("AnswerFriendRequest", pb.FriendAnswer(username=peer, accept=accept))
        else:  # SendFriendRequest | RemoveFriend | Block | Unblock
            self.api.call(action, pb.UserRef(username=peer))

    # ---------- обычные чаты ----------

    def send_text(self, peer: str, text: str) -> ChatMessage:
        text = text.strip()[:TEXT_MAX]
        payload = json.dumps({"t": "text", "body": text}).encode()
        header, ciphertext = regular.encrypt(self.keys, self.me, self.bundle(peer), payload)
        reply = self.api.call("SendMessage", pb.Envelope(recipient=peer, kind=pb.REGULAR, header=header,
                                                         ciphertext=ciphertext))
        return ChatMessage(reply.id, peer, True, text, reply.sent_at)

    def history(self, peer: str, before_id: int = 0) -> list[ChatMessage]:
        reply = self.api.call("History", pb.HistoryRequest(peer=peer, before_id=before_id, limit=100))
        return [self._open_regular(m) for m in reply.messages]

    def _open_regular(self, env: pb.Envelope) -> ChatMessage:
        outgoing = env.sender == self.me
        peer = env.recipient if outgoing else env.sender
        message = ChatMessage(env.id, peer, outgoing, "", env.sent_at)
        if outgoing:
            sign_key = pub_bytes(self.keys.identity_sign)
        else:
            sender_key = regular.sender_key_of(env.header)
            sign_key = self._sign_key(peer, sender_key)
            if sign_key is None:  # ключа ещё не знаем — спросим у сервера
                try:
                    self.bundle(peer, refresh=True)
                except ApiError:
                    pass
                sign_key = self._sign_key(peer, sender_key)
        try:
            if sign_key is None:
                raise regular.DecryptError("Неизвестный ключ отправителя.")
            payload = json.loads(regular.decrypt(self.keys, self.me, env.sender, env.recipient, env.header,
                                                 env.ciphertext, sign_key))
            message.text = str(payload.get("body", ""))[:TEXT_MAX]
        except (regular.DecryptError, ValueError) as exc:
            message.text, message.error = str(exc) or "Не удалось расшифровать сообщение.", True
        return message

    # ---------- секретные чаты ----------

    def secret_peers(self) -> list[str]:
        with self.lock:
            return sorted(self.store.data["secret"])

    def secret_messages(self, peer: str) -> list[ChatMessage]:
        with self.lock:
            chat = self.store.data["secret"].get(peer)
            return [ChatMessage(**m) for m in chat["messages"]] if chat else []

    def secret_ttl(self, peer: str) -> int:
        with self.lock:
            return self.store.data["secret"].get(peer, {}).get("ttl", 0)

    def set_secret_ttl(self, peer: str, ttl: int) -> None:
        with self.lock:
            self.store.data["secret"][peer]["ttl"] = ttl if ttl in SECRET_TTL_CHOICES else 0
            self.store.save()

    def start_secret(self, peer: str) -> None:
        """Начинает секретный чат: X3DH по ключам собеседника и первое сообщение «start»."""
        session = ratchet.Ratchet.start(self.keys, self.bundle(peer, refresh=True))
        with self.lock:
            self.store.data["secret"][peer] = {"ratchet": session.to_dict(), "init_ek": session.init["ek"],
                                               "ttl": 0, "messages": []}
            self._system(peer, "Вы начали секретный чат. Сообщения видны только на этом устройстве.")
        self._send_secret(peer, {"t": "start"})

    def send_secret(self, peer: str, text: str) -> ChatMessage:
        text = text.strip()[:TEXT_MAX]
        ttl = self.secret_ttl(peer)
        reply = self._send_secret(peer, {"t": "text", "body": text, "ttl": ttl})
        message = ChatMessage(reply.id, peer, True, text, reply.sent_at, secret=True, ttl=ttl,
                              read_at=reply.sent_at if ttl else 0)
        with self.lock:
            self.store.data["secret"][peer]["messages"].append(message.to_dict())
            self.store.save()
        return message

    def close_secret(self, peer: str) -> None:
        """Закрывает чат у обоих и стирает его с устройства вместе с ключами храповика."""
        try:
            self._send_secret(peer, {"t": "close"})
        except (ApiError, KeyError):
            pass
        with self.lock:
            self.store.data["secret"].pop(peer, None)
            self.store.save()

    def _send_secret(self, peer: str, payload: dict) -> pb.SendReply:
        with self.lock:
            chat = self.store.data["secret"][peer]
            session = ratchet.Ratchet.from_dict(chat["ratchet"])
            header, ciphertext = session.encrypt(json.dumps(payload).encode())
            chat["ratchet"] = session.to_dict()  # ключ сообщения уже стёрт, сохраняем новое состояние
            self.store.save()
        return self.api.call("SendMessage", pb.Envelope(recipient=peer, kind=pb.SECRET, header=header,
                                                        ciphertext=ciphertext))

    def _open_secret(self, env: pb.Envelope) -> list[Update]:
        peer = env.sender
        try:
            header = json.loads(env.header)
        except ValueError:
            return []
        with self.lock:
            chat = self.store.data["secret"].get(peer)
            init = header.get("init")
            updates = []
            if init and (chat is None or chat.get("init_ek") != init.get("ek")):
                # Новый секретный чат. Если оба начали одновременно, остаётся тот,
                # кого начал пользователь с меньшим именем: так обе стороны выберут одно и то же.
                mine_pending = chat is not None and chat["ratchet"].get("init") is not None
                if mine_pending and self.me < peer:
                    return []
                if ratchet.Ratchet.initiator_identity(header) != self._peer_identity(peer):
                    return []  # первое сообщение подписано не тем ключом, что сервер отдаёт для собеседника
                try:
                    session = ratchet.Ratchet.accept(self.keys, header)
                except (ratchet.RatchetError, KeyError, ValueError):
                    return []
                chat = {"ratchet": session.to_dict(), "init_ek": init.get("ek"), "ttl": 0, "messages": []}
                self.store.data["secret"][peer] = chat
            elif chat is None:
                return []

            session = ratchet.Ratchet.from_dict(chat["ratchet"])
            try:
                payload = json.loads(session.decrypt(env.header, env.ciphertext))
            except (ratchet.RatchetError, ValueError):
                return [Update("message", peer, ChatMessage(env.id, peer, False, "Не удалось расшифровать "
                               "сообщение секретного чата.", env.sent_at, secret=True, error=True))]
            chat["ratchet"] = session.to_dict()

            kind = payload.get("t")
            if kind == "start":
                self._system(peer, f"{peer} начал(а) секретный чат. Сверьте код безопасности.")
                updates.append(Update("secret_started", peer))
            elif kind == "close":
                self.store.data["secret"].pop(peer, None)
                updates.append(Update("secret_closed", peer))
            elif kind == "text":
                ttl = payload.get("ttl", 0)
                message = ChatMessage(env.id, peer, False, str(payload.get("body", ""))[:TEXT_MAX], env.sent_at,
                                      secret=True, ttl=ttl if ttl in SECRET_TTL_CHOICES else 0)
                chat["messages"].append(message.to_dict())
                updates.append(Update("message", peer, message))
            self.store.save()
            return updates

    def _peer_identity(self, peer: str) -> bytes | None:
        try:
            return self.bundle(peer, refresh=True).identity_dh
        except ApiError:
            return None

    def _system(self, peer: str, text: str) -> None:
        message = ChatMessage(-int(time.time() * 1000), peer, False, text, int(time.time()), secret=True, system=True)
        self.store.data["secret"][peer]["messages"].append(message.to_dict())
        self.store.save()

    def mark_read(self, peer: str) -> None:
        """Чат открыт на экране: запускаем таймеры самоуничтожения входящих сообщений."""
        now = int(time.time())
        with self.lock:
            chat = self.store.data["secret"].get(peer)
            if not chat:
                return
            changed = False
            for m in chat["messages"]:
                if m["ttl"] and not m["read_at"]:
                    m["read_at"], changed = now, True
            if changed:
                self.store.save()

    def purge_expired(self) -> set[str]:
        """Удаляет сообщения с истёкшим таймером. Возвращает чаты, где что-то исчезло."""
        now = int(time.time())
        touched = set()
        with self.lock:
            for peer, chat in self.store.data["secret"].items():
                keep = [m for m in chat["messages"] if not (m["ttl"] and m["read_at"] and m["read_at"] + m["ttl"] <= now)]
                if len(keep) != len(chat["messages"]):
                    chat["messages"] = keep
                    touched.add(peer)
            if touched:
                self.store.save()
        return touched

    # ---------- события с сервера ----------

    def handle_event(self, event: pb.Event) -> list[Update]:
        if event.HasField("contact"):
            contact = event.contact
            if contact.state == pb.KEY_CHANGED:
                updates = [Update("key_changed", contact.username)]
                with self.lock:
                    self._bundles.pop(contact.username, None)
                    if contact.username in self.store.data["secret"]:
                        # Новое устройство собеседника не знает ключей этого чата
                        self.store.data["secret"].pop(contact.username)
                        self.store.save()
                        updates.append(Update("secret_closed", contact.username))
                return updates
            with self.lock:
                if contact.state == pb.NONE:
                    self.contacts.pop(contact.username, None)
                else:
                    self.contacts[contact.username] = contact.state
            return [Update("contacts", contact.username)]

        env = event.message
        if env.kind == pb.SECRET:
            updates = self._open_secret(env)
            try:
                self.api.call("Acknowledge", pb.AckRequest(ids=[env.id]))  # сервер сотрёт шифротекст
            except ApiError:
                pass
            return updates
        message = self._open_regular(env)
        return [Update("message", message.peer, message)]
