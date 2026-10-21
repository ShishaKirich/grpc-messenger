"""Тесты шифрования: обычные чаты, Double Ratchet, хранилище ключей, код безопасности."""
import json
import random

import pytest

from e2e import ratchet as rt
from e2e import regular
from e2e.keys import DeviceKeys, PublicBundle, safety_number
from e2e.keystore import Keystore, WrongPassword
from e2e.primitives import pub_bytes

ALICE, BOB = DeviceKeys.generate(), DeviceKeys.generate()


# ---------- обычные чаты ----------

def test_regular_roundtrip_for_recipient_and_sender():
    header, ct = regular.encrypt(ALICE, "alice", BOB.public("bob"), "привет".encode())
    sign = pub_bytes(ALICE.identity_sign)
    assert regular.decrypt(BOB, "bob", "alice", "bob", header, ct, sign) == "привет".encode()
    # отправитель видит своё сообщение в истории
    assert regular.decrypt(ALICE, "alice", "alice", "bob", header, ct, sign) == "привет".encode()


def test_regular_third_party_cannot_read():
    eve = DeviceKeys.generate()
    header, ct = regular.encrypt(ALICE, "alice", BOB.public("bob"), b"secret")
    with pytest.raises(regular.DecryptError):
        regular.decrypt(eve, "bob", "alice", "bob", header, ct, pub_bytes(ALICE.identity_sign))


def test_regular_server_cannot_change_sender_or_text():
    header, ct = regular.encrypt(ALICE, "alice", BOB.public("bob"), b"pay 10")
    sign = pub_bytes(ALICE.identity_sign)
    with pytest.raises(regular.DecryptError):  # сервер выдаёт сообщение за письмо от mallory
        regular.decrypt(BOB, "bob", "mallory", "bob", header, ct, sign)
    tampered = bytearray(ct)
    tampered[-1] ^= 1
    with pytest.raises(regular.DecryptError):
        regular.decrypt(BOB, "bob", "alice", "bob", header, bytes(tampered), sign)
    mallory = DeviceKeys.generate()  # подпись чужим ключом не проходит
    with pytest.raises(regular.DecryptError):
        regular.decrypt(BOB, "bob", "alice", "bob", header, ct, pub_bytes(mallory.identity_sign))


# ---------- секретные чаты ----------

def pair():
    a = rt.Ratchet.start(ALICE, BOB.public("bob"))
    header, ct = a.encrypt(b"start")
    b = rt.Ratchet.accept(BOB, json.loads(header))
    assert b.decrypt(header, ct) == b"start"
    return a, b


def test_ratchet_conversation():
    a, b = pair()
    for i in range(5):
        h, c = b.encrypt(f"b{i}".encode())
        assert a.decrypt(h, c) == f"b{i}".encode()
        h, c = a.encrypt(f"a{i}".encode())
        assert b.decrypt(h, c) == f"a{i}".encode()
    assert a.init is None  # после ответа X3DH-данные больше не отправляются


def test_ratchet_out_of_order():
    a, b = pair()
    msgs = [a.encrypt(f"m{i}".encode()) for i in range(10)]
    order = list(range(10))
    random.Random(1).shuffle(order)
    for i in order:
        assert b.decrypt(*msgs[i]) == f"m{i}".encode()


def test_ratchet_replay_rejected():
    a, b = pair()
    h, c = a.encrypt(b"once")
    assert b.decrypt(h, c) == b"once"
    with pytest.raises(rt.RatchetError):  # ключ сообщения уже стёрт
        b.decrypt(h, c)


def test_ratchet_forward_secrecy():
    """Кража текущего состояния не раскрывает уже прочитанные сообщения."""
    a, b = pair()
    old = a.encrypt(b"old secret")
    assert b.decrypt(*old) == b"old secret"
    stolen = rt.Ratchet.from_dict(b.to_dict())
    with pytest.raises(rt.RatchetError):
        stolen.decrypt(*old)


def test_ratchet_tampering_keeps_state():
    a, b = pair()
    h, c = a.encrypt(b"hello")
    with pytest.raises(rt.RatchetError):
        b.decrypt(h, c[:-1] + bytes([c[-1] ^ 1]))
    assert b.decrypt(h, c) == b"hello"  # подделка не сломала чат


def test_ratchet_state_survives_restart():
    a, b = pair()
    b = rt.Ratchet.from_dict(json.loads(json.dumps(b.to_dict())))
    h, c = a.encrypt(b"after restart")
    assert b.decrypt(h, c) == b"after restart"


def test_ratchet_rejects_forged_prekey():
    bundle = BOB.public("bob")
    forged = PublicBundle(bundle.username, bundle.identity_dh, bundle.identity_sign,
                          pub_bytes(DeviceKeys.generate().signed_prekey), bundle.prekey_signature)
    with pytest.raises(rt.RatchetError):
        rt.Ratchet.start(ALICE, forged)


# ---------- хранилище и код безопасности ----------

def test_keystore(tmp_path):
    Keystore.create(tmp_path, "alice", "pass-1", {"keys": ALICE.to_dict()})
    store = Keystore.open(tmp_path, "alice", "pass-1")
    assert DeviceKeys.from_dict(store.data["keys"]).public("a") == ALICE.public("a")
    with pytest.raises(WrongPassword):
        Keystore.open(tmp_path, "alice", "wrong")
    store.change_password("pass-2")
    assert Keystore.open(tmp_path, "alice", "pass-2").data["keys"] == ALICE.to_dict()
    assert b"identity" not in (tmp_path / "alice.bin").read_bytes()  # на диске ничего в открытом виде


def test_safety_number_is_symmetric_and_detects_mitm():
    a, b = ALICE.public("alice"), BOB.public("bob")
    number = safety_number(a, b)
    assert number == safety_number(b, a)
    assert len(number.replace(" ", "")) == 60
    mitm = DeviceKeys.generate().public("bob")
    assert safety_number(a, mitm) != number
