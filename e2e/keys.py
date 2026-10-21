"""Ключи устройства и код безопасности.

У каждого устройства три пары ключей, созданные на самом устройстве:
  identity_dh    (X25519)  — долговременный ключ для шифрования
  identity_sign  (Ed25519) — подписывает prekey и сообщения обычных чатов
  signed_prekey  (X25519)  — для начала секретного чата (X3DH), подписан identity_sign
На сервер уходят только открытые половины (KeyBundle).
"""
import hashlib
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .primitives import b64, priv_bytes, pub_bytes, unb64


@dataclass(frozen=True)
class PublicBundle:
    """Открытые ключи собеседника, как их отдаёт сервер (GetKeys)."""
    username: str
    identity_dh: bytes
    identity_sign: bytes
    signed_prekey: bytes
    prekey_signature: bytes
    key_id: int = 0

    def verify_prekey(self) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(self.identity_sign).verify(self.prekey_signature, self.signed_prekey)
            return True
        except InvalidSignature:
            return False

    @classmethod
    def from_proto(cls, msg) -> "PublicBundle":
        return cls(msg.username, msg.identity_dh, msg.identity_sign, msg.signed_prekey, msg.prekey_signature,
                   msg.key_id)

    def to_dict(self) -> dict:
        return {"username": self.username, "identity_dh": b64(self.identity_dh),
                "identity_sign": b64(self.identity_sign), "signed_prekey": b64(self.signed_prekey),
                "prekey_signature": b64(self.prekey_signature), "key_id": self.key_id}

    @classmethod
    def from_dict(cls, d: dict) -> "PublicBundle":
        return cls(d["username"], unb64(d["identity_dh"]), unb64(d["identity_sign"]), unb64(d["signed_prekey"]),
                   unb64(d["prekey_signature"]), d.get("key_id", 0))


@dataclass
class DeviceKeys:
    identity_dh: X25519PrivateKey
    identity_sign: Ed25519PrivateKey
    signed_prekey: X25519PrivateKey

    @classmethod
    def generate(cls) -> "DeviceKeys":
        return cls(X25519PrivateKey.generate(), Ed25519PrivateKey.generate(), X25519PrivateKey.generate())

    @property
    def prekey_signature(self) -> bytes:
        return self.identity_sign.sign(pub_bytes(self.signed_prekey))

    def public(self, username: str) -> PublicBundle:
        return PublicBundle(username, pub_bytes(self.identity_dh), pub_bytes(self.identity_sign),
                            pub_bytes(self.signed_prekey), self.prekey_signature)

    def to_dict(self) -> dict:
        return {"identity_dh": b64(priv_bytes(self.identity_dh)),
                "identity_sign": b64(priv_bytes(self.identity_sign)),
                "signed_prekey": b64(priv_bytes(self.signed_prekey))}

    @classmethod
    def from_dict(cls, d: dict) -> "DeviceKeys":
        return cls(X25519PrivateKey.from_private_bytes(unb64(d["identity_dh"])),
                   Ed25519PrivateKey.from_private_bytes(unb64(d["identity_sign"])),
                   X25519PrivateKey.from_private_bytes(unb64(d["signed_prekey"])))


def safety_number(a: PublicBundle, b: PublicBundle) -> str:
    """Код безопасности пары собеседников: 60 цифр группами по 5, у обоих одинаковый.

    Если цифры на двух устройствах совпали (сверили лично или по телефону), значит
    сервер не подменил ключи и посредника в переписке нет.
    """
    def part(bundle: PublicBundle) -> bytes:
        digest = bundle.username.encode() + b"\x00" + bundle.identity_dh + bundle.identity_sign
        for _ in range(5200):  # растягивание, как в Signal: подобрать ключ с похожим кодом дорого
            digest = hashlib.sha512(digest + bundle.identity_dh).digest()
        return digest[:30]

    data = b"".join(sorted([part(a), part(b)]))  # порядок не зависит от того, кто считает
    return " ".join(f"{int.from_bytes(data[i:i + 5], 'big') % 100000:05d}" for i in range(0, 60, 5))
