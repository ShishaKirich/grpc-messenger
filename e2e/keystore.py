"""Зашифрованное хранилище на устройстве.

В одном файле keystore/<имя>.bin лежит всё секретное, что есть у клиента:
закрытые ключи устройства, состояния секретных чатов, их сообщения и известные
ключи собеседников. Файл зашифрован ChaCha20-Poly1305 ключом, который выводится из
пароля через Argon2id (64 МБ памяти) — украденный файл без пароля бесполезен,
а перебор паролей очень дорогой.

Запись атомарная (временный файл + замена), чтобы сбой посреди записи не испортил ключи.
"""
import json
import os
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag

from .primitives import b64, open_sealed, seal, unb64

FORMAT = "les-keystore-v1"
ARGON_TIME, ARGON_MEMORY_KIB, ARGON_LANES = 3, 64 * 1024, 1


class WrongPassword(Exception):
    """Не удалось открыть хранилище: другой пароль (например, его сменили на сайте) или файл повреждён."""


def derive_key(password: str, salt: bytes) -> bytes:
    return hash_secret_raw(password.encode(), salt, time_cost=ARGON_TIME, memory_cost=ARGON_MEMORY_KIB,
                           parallelism=ARGON_LANES, hash_len=32, type=Type.ID)


class Keystore:
    def __init__(self, path: Path, username: str, key: bytes, salt: bytes, data: dict) -> None:
        self.path, self.username, self._key, self._salt = path, username, key, salt
        self.data = data

    @staticmethod
    def path_for(folder: Path, username: str) -> Path:
        return folder / f"{username.lower()}.bin"

    @classmethod
    def exists(cls, folder: Path, username: str) -> bool:
        return cls.path_for(folder, username).exists()

    @classmethod
    def create(cls, folder: Path, username: str, password: str, data: dict) -> "Keystore":
        folder.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        store = cls(cls.path_for(folder, username), username, derive_key(password, salt), salt, data)
        store.save()
        return store

    @classmethod
    def open(cls, folder: Path, username: str, password: str) -> "Keystore":
        path = cls.path_for(folder, username)
        try:
            outer = json.loads(path.read_text(encoding="utf-8"))
            salt = unb64(outer["salt"])
            key = derive_key(password, salt)
            data = json.loads(open_sealed(key, unb64(outer["data"]), cls._ad(username)))
        except (InvalidTag, KeyError, ValueError):
            raise WrongPassword from None
        return cls(path, username, key, salt, data)

    def change_password(self, new_password: str) -> None:
        self._salt = os.urandom(16)
        self._key = derive_key(new_password, self._salt)
        self.save()

    def save(self) -> None:
        sealed = seal(self._key, json.dumps(self.data).encode(), self._ad(self.username))
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"format": FORMAT, "salt": b64(self._salt), "data": b64(sealed)}), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _ad(username: str) -> bytes:
        return f"{FORMAT}|{username.lower()}".encode()
