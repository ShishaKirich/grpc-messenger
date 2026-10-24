"""Секретные чаты: X3DH + Double Ratchet (по спецификациям Signal).

X3DH — как два устройства получают общий секрет, даже если второе сейчас не в сети:
инициатор берёт с сервера открытые ключи собеседника (identity + подписанный prekey)
и делает три обмена Диффи — Хеллмана со своим долговременным и одноразовым ключами.
https://signal.org/docs/specifications/x3dh/

Double Ratchet — каждое сообщение шифруется новым ключом, а старые ключи сразу
стираются. Что это даёт:
  * прямая секретность: украденный сегодня ключ не расшифрует вчерашние сообщения;
  * восстановление после взлома: с каждым ответом собеседника в цепочку подмешивается
    новый Диффи — Хеллман, и украденное состояние быстро становится бесполезным.
https://signal.org/docs/specifications/doubleratchet/

Сервер видит только шифротекст и стирает его сразу после доставки.
"""
import json
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .keys import DeviceKeys, PublicBundle
from .primitives import b64, dh, hkdf, hmac_sha256, open_sealed, priv_bytes, pub_bytes, seal, unb64

MAX_SKIP = 100   # сколько пропущенных (ещё не пришедших) сообщений готовы ждать в одной цепочке
X3DH_INFO = b"LesShishek-X3DH"
RATCHET_INFO = b"LesShishek-ratchet"


class RatchetError(Exception):
    """Сообщение не расшифровалось: подделка, повтор или сломанное состояние чата."""


# ---------- функции вывода ключей ----------

def kdf_root(root_key: bytes, dh_out: bytes) -> tuple[bytes, bytes]:
    """Шаг «корневого» храповика: новый корневой ключ и новый ключ цепочки."""
    out = hkdf(dh_out, info=RATCHET_INFO, length=64, salt=root_key)
    return out[:32], out[32:]


def kdf_chain(chain_key: bytes) -> tuple[bytes, bytes]:
    """Шаг цепочки: ключ для одного сообщения и следующий ключ цепочки."""
    return hmac_sha256(chain_key, b"\x02"), hmac_sha256(chain_key, b"\x01")


def _message_key_material(message_key: bytes) -> bytes:
    return hkdf(message_key, info=b"LesShishek-message")


# ---------- X3DH ----------

def x3dh_initiator(my: DeviceKeys, peer: PublicBundle) -> tuple[bytes, bytes, bytes]:
    """Возвращает (общий секрет, AD, открытый одноразовый ключ) для первого сообщения."""
    if not peer.verify_prekey():
        raise RatchetError("Подпись prekey собеседника не сходится — ключи могли подменить.")
    ephemeral = X25519PrivateKey.generate()
    dh1 = dh(my.identity_dh, peer.signed_prekey)
    dh2 = dh(ephemeral, peer.identity_dh)
    dh3 = dh(ephemeral, peer.signed_prekey)
    secret = hkdf(b"\xff" * 32 + dh1 + dh2 + dh3, info=X3DH_INFO, salt=b"\x00" * 32)
    ad = pub_bytes(my.identity_dh) + peer.identity_dh
    return secret, ad, pub_bytes(ephemeral)


def x3dh_responder(my: DeviceKeys, peer_identity_dh: bytes, peer_ephemeral: bytes) -> tuple[bytes, bytes]:
    dh1 = dh(my.signed_prekey, peer_identity_dh)
    dh2 = dh(my.identity_dh, peer_ephemeral)
    dh3 = dh(my.signed_prekey, peer_ephemeral)
    secret = hkdf(b"\xff" * 32 + dh1 + dh2 + dh3, info=X3DH_INFO, salt=b"\x00" * 32)
    ad = peer_identity_dh + pub_bytes(my.identity_dh)
    return secret, ad


# ---------- Double Ratchet ----------

@dataclass
class Ratchet:
    root_key: bytes
    ad: bytes                               # identity-ключи обоих: привязывают шифр к этой паре
    dh_self: X25519PrivateKey
    dh_remote: bytes | None = None
    send_chain: bytes | None = None
    recv_chain: bytes | None = None
    sent: int = 0                           # номер следующего отправляемого сообщения в цепочке
    received: int = 0
    previous_sent: int = 0                  # длина предыдущей цепочки отправки
    skipped: dict[str, bytes] = field(default_factory=dict)   # "ключ_DH:номер" -> ключ сообщения
    init: dict | None = None                # данные X3DH: идут в заголовке, пока собеседник не ответил

    # --- создание ---

    @classmethod
    def start(cls, my: DeviceKeys, peer: PublicBundle) -> "Ratchet":
        """Инициатор секретного чата."""
        secret, ad, eph_pub = x3dh_initiator(my, peer)
        dh_self = X25519PrivateKey.generate()
        root_key, send_chain = kdf_root(secret, dh(dh_self, peer.signed_prekey))
        return cls(root_key=root_key, ad=ad, dh_self=dh_self, dh_remote=peer.signed_prekey, send_chain=send_chain,
                   init={"ik": b64(pub_bytes(my.identity_dh)), "ek": b64(eph_pub),
                         "spk": b64(peer.signed_prekey)})

    @classmethod
    def accept(cls, my: DeviceKeys, header: dict) -> "Ratchet":
        """Получатель первого сообщения секретного чата."""
        init = header.get("init")
        if not init or unb64(init["spk"]) != pub_bytes(my.signed_prekey):
            raise RatchetError("Сообщение начинает секретный чат с другим ключом устройства.")
        secret, ad = x3dh_responder(my, unb64(init["ik"]), unb64(init["ek"]))
        # Первая пара храповика у получателя — его signed prekey
        signed_prekey = X25519PrivateKey.from_private_bytes(priv_bytes(my.signed_prekey))
        return cls(root_key=secret, ad=ad, dh_self=signed_prekey)

    @staticmethod
    def initiator_identity(header: dict) -> bytes | None:
        init = header.get("init")
        return unb64(init["ik"]) if init else None

    # --- шифрование ---

    def encrypt(self, plaintext: bytes) -> tuple[bytes, bytes]:
        """Возвращает (header, ciphertext). Ключ сообщения используется один раз и забывается."""
        message_key, self.send_chain = kdf_chain(self.send_chain)
        header = {"dh": b64(pub_bytes(self.dh_self)), "pn": self.previous_sent, "n": self.sent}
        if self.init:
            header["init"] = self.init
        self.sent += 1
        header_bytes = json.dumps(header, sort_keys=True).encode()
        return header_bytes, seal(_message_key_material(message_key), plaintext, self.ad + header_bytes)

    def decrypt(self, header_bytes: bytes, ciphertext: bytes) -> bytes:
        """Расшифровывает. Если сообщение подделано, состояние не меняется."""
        try:
            header = json.loads(header_bytes)
            remote = unb64(header["dh"])
            number, previous = int(header["n"]), int(header["pn"])
        except (ValueError, KeyError, TypeError):
            raise RatchetError("Неверный заголовок сообщения.") from None

        snapshot = self.to_dict()  # откат, если расшифровать не получится
        try:
            skipped_key = self.skipped.pop(f"{b64(remote)}:{number}", None)
            if skipped_key is not None:
                message_key = skipped_key
            else:
                if remote != self.dh_remote:
                    self._skip(previous)
                    self._dh_step(remote)
                self._skip(number)
                message_key, self.recv_chain = kdf_chain(self.recv_chain)
                self.received += 1
            plaintext = open_sealed(_message_key_material(message_key), ciphertext, self.ad + header_bytes)
        except (InvalidTag, RatchetError) as exc:
            self._restore(snapshot)
            raise RatchetError("Не удалось расшифровать сообщение секретного чата.") from exc
        self.init = None  # собеседник ответил — X3DH-данные в заголовке больше не нужны
        return plaintext

    def _skip(self, until: int) -> None:
        """Запоминает ключи сообщений, которые ещё не пришли (сообщения могут прийти не по порядку)."""
        if self.recv_chain is None:
            return
        if until - self.received > MAX_SKIP:
            raise RatchetError("Слишком много пропущенных сообщений.")
        while self.received < until:
            message_key, self.recv_chain = kdf_chain(self.recv_chain)
            self.skipped[f"{b64(self.dh_remote)}:{self.received}"] = message_key
            self.received += 1
        while len(self.skipped) > MAX_SKIP:  # старые пропущенные ключи выбрасываем
            self.skipped.pop(next(iter(self.skipped)))

    def _dh_step(self, remote: bytes) -> None:
        """Новый открытый ключ собеседника: два шага корневого храповика."""
        self.previous_sent, self.sent, self.received = self.sent, 0, 0
        self.dh_remote = remote
        self.root_key, self.recv_chain = kdf_root(self.root_key, dh(self.dh_self, remote))
        self.dh_self = X25519PrivateKey.generate()
        self.root_key, self.send_chain = kdf_root(self.root_key, dh(self.dh_self, remote))

    # --- сохранение (в зашифрованное хранилище устройства) ---

    def to_dict(self) -> dict:
        opt = lambda v: b64(v) if v is not None else None  # noqa: E731
        return {"root_key": b64(self.root_key), "ad": b64(self.ad), "dh_self": b64(priv_bytes(self.dh_self)),
                "dh_remote": opt(self.dh_remote), "send_chain": opt(self.send_chain),
                "recv_chain": opt(self.recv_chain), "sent": self.sent, "received": self.received,
                "previous_sent": self.previous_sent, "skipped": {k: b64(v) for k, v in self.skipped.items()},
                "init": self.init}

    @classmethod
    def from_dict(cls, d: dict) -> "Ratchet":
        opt = lambda v: unb64(v) if v is not None else None  # noqa: E731
        return cls(root_key=unb64(d["root_key"]), ad=unb64(d["ad"]),
                   dh_self=X25519PrivateKey.from_private_bytes(unb64(d["dh_self"])),
                   dh_remote=opt(d["dh_remote"]), send_chain=opt(d["send_chain"]), recv_chain=opt(d["recv_chain"]),
                   sent=d["sent"], received=d["received"], previous_sent=d["previous_sent"],
                   skipped={k: unb64(v) for k, v in d["skipped"].items()}, init=d["init"])

    def _restore(self, d: dict) -> None:
        self.__dict__.update(Ratchet.from_dict(d).__dict__)
