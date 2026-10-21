"""Криптографические примитивы. Всё из библиотеки cryptography, ничего самописного.

X25519            — обмен ключами (Диффи — Хеллман на эллиптической кривой)
Ed25519           — подписи
HKDF-SHA256       — вывод ключей из общего секрета
ChaCha20-Poly1305 — шифрование с проверкой целостности (AEAD)
"""
import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RAW = serialization.Encoding.Raw


def pub_bytes(key: X25519PrivateKey | Ed25519PrivateKey | X25519PublicKey | Ed25519PublicKey) -> bytes:
    if isinstance(key, (X25519PrivateKey, Ed25519PrivateKey)):
        key = key.public_key()
    return key.public_bytes(RAW, serialization.PublicFormat.Raw)


def priv_bytes(key: X25519PrivateKey | Ed25519PrivateKey) -> bytes:
    return key.private_bytes(RAW, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def dh(private: X25519PrivateKey, public: bytes) -> bytes:
    return private.exchange(X25519PublicKey.from_public_bytes(public))


def hkdf(ikm: bytes, info: bytes, length: int = 32, salt: bytes | None = None) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def seal(key: bytes, plaintext: bytes, ad: bytes) -> bytes:
    """Шифрует со случайным nonce. Результат: nonce (12 байт) + шифротекст + тег."""
    nonce = os.urandom(12)
    return nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, ad)


def open_sealed(key: bytes, data: bytes, ad: bytes) -> bytes:
    """Расшифровывает; если данные подменены или ключ не тот — InvalidTag."""
    return ChaCha20Poly1305(key).decrypt(data[:12], data[12:], ad)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode(), validate=True)
