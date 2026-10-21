"""Шифрование обычных чатов.

Каждое сообщение шифруется своим случайным ключом (ChaCha20-Poly1305). Этот ключ
«заворачивается» дважды: для устройства получателя и для своего устройства (чтобы
видеть собственные сообщения в истории). Для заворачивания берётся одноразовая пара
X25519 и Диффи — Хеллман с долговременным ключом читателя.

Отправитель подписывает сообщение ключом Ed25519, поэтому сервер не может ни прочитать
текст, ни подделать сообщение от чужого имени, ни переслать его другому человеку
(имена отправителя и получателя входят в подпись и в AD шифра).

Чем это слабее секретного чата: при краже долговременного ключа устройства можно
расшифровать всю сохранённую на сервере историю. В секретных чатах этого нет (см. ratchet.py).
"""
import json
import os

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .keys import DeviceKeys, PublicBundle
from .primitives import b64, dh, hkdf, open_sealed, pub_bytes, seal, unb64

VERSION = 1


class DecryptError(Exception):
    """Сообщение нельзя расшифровать или проверить: подделано, повреждено или для другого устройства."""


def _ad(sender: str, recipient: str) -> bytes:
    return f"regular/v{VERSION}|{sender}|{recipient}".encode()


def _wrap_key(shared: bytes, ephemeral_pub: bytes, reader_pub: bytes) -> bytes:
    return hkdf(shared, info=b"LesShishek-regular-wrap" + ephemeral_pub + reader_pub)


def encrypt(my_keys: DeviceKeys, me: str, peer: PublicBundle, plaintext: bytes) -> tuple[bytes, bytes]:
    """Возвращает (header, ciphertext) для Envelope."""
    ad = _ad(me, peer.username)
    message_key = os.urandom(32)
    ciphertext = seal(message_key, plaintext, ad)

    ephemeral = X25519PrivateKey.generate()
    eph_pub = pub_bytes(ephemeral)
    my_pub = pub_bytes(my_keys.identity_dh)
    wrapped = {}
    for role, reader_pub in (("to_recipient", peer.identity_dh), ("to_sender", my_pub)):
        wrap = _wrap_key(dh(ephemeral, reader_pub), eph_pub, reader_pub)
        wrapped[role] = b64(seal(wrap, message_key, ad))

    header = {"v": VERSION, "eph": b64(eph_pub), "recipient_key": b64(peer.identity_dh),
              "sender_key": b64(my_pub), **wrapped}
    body = json.dumps(header, sort_keys=True).encode()
    signature = my_keys.identity_sign.sign(ad + body + ciphertext)
    return json.dumps({"h": header, "sig": b64(signature)}).encode(), ciphertext


def decrypt(my_keys: DeviceKeys, me: str, sender: str, recipient: str, header: bytes, ciphertext: bytes,
            sender_sign_key: bytes) -> bytes:
    """Расшифровывает сообщение, где я отправитель или получатель.

    sender_sign_key — известный нам открытый ключ подписи отправителя (Ed25519).
    """
    ad = _ad(sender, recipient)
    try:
        outer = json.loads(header)
        h = outer["h"]
        body = json.dumps(h, sort_keys=True).encode()
        Ed25519PublicKey.from_public_bytes(sender_sign_key).verify(unb64(outer["sig"]), ad + body + ciphertext)

        my_pub = pub_bytes(my_keys.identity_dh)
        role = "to_sender" if me == sender else "to_recipient"
        expected_key = h["sender_key"] if role == "to_sender" else h["recipient_key"]
        if unb64(expected_key) != my_pub:
            raise DecryptError("Сообщение зашифровано для другого устройства.")
        eph_pub = unb64(h["eph"])
        wrap = _wrap_key(dh(my_keys.identity_dh, eph_pub), eph_pub, my_pub)
        message_key = open_sealed(wrap, unb64(h[role]), ad)
        return open_sealed(message_key, ciphertext, ad)
    except DecryptError:
        raise
    except InvalidSignature:
        raise DecryptError("Подпись не сходится: сообщение подделано или ключ собеседника изменился.") from None
    except (InvalidTag, KeyError, ValueError, TypeError):
        raise DecryptError("Сообщение повреждено.") from None
