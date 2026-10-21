from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SecondFactor(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SECOND_FACTOR_UNSPECIFIED: _ClassVar[SecondFactor]
    EMAIL_CODE: _ClassVar[SecondFactor]
    TOTP: _ClassVar[SecondFactor]

class ContactState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CONTACT_STATE_UNSPECIFIED: _ClassVar[ContactState]
    FRIEND: _ClassVar[ContactState]
    INCOMING: _ClassVar[ContactState]
    OUTGOING: _ClassVar[ContactState]
    BLOCKED: _ClassVar[ContactState]
    NONE: _ClassVar[ContactState]
    KEY_CHANGED: _ClassVar[ContactState]

class ChatKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CHAT_KIND_UNSPECIFIED: _ClassVar[ChatKind]
    REGULAR: _ClassVar[ChatKind]
    SECRET: _ClassVar[ChatKind]
SECOND_FACTOR_UNSPECIFIED: SecondFactor
EMAIL_CODE: SecondFactor
TOTP: SecondFactor
CONTACT_STATE_UNSPECIFIED: ContactState
FRIEND: ContactState
INCOMING: ContactState
OUTGOING: ContactState
BLOCKED: ContactState
NONE: ContactState
KEY_CHANGED: ContactState
CHAT_KIND_UNSPECIFIED: ChatKind
REGULAR: ChatKind
SECRET: ChatKind

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class LoginRequest(_message.Message):
    __slots__ = ("email", "password", "device_name")
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    PASSWORD_FIELD_NUMBER: _ClassVar[int]
    DEVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    email: str
    password: str
    device_name: str
    def __init__(self, email: _Optional[str] = ..., password: _Optional[str] = ..., device_name: _Optional[str] = ...) -> None: ...

class LoginReply(_message.Message):
    __slots__ = ("challenge_id", "method", "expires_at")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    method: SecondFactor
    expires_at: int
    def __init__(self, challenge_id: _Optional[str] = ..., method: _Optional[_Union[SecondFactor, str]] = ..., expires_at: _Optional[int] = ...) -> None: ...

class VerifyRequest(_message.Message):
    __slots__ = ("challenge_id", "code")
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    code: str
    def __init__(self, challenge_id: _Optional[str] = ..., code: _Optional[str] = ...) -> None: ...

class VerifyReply(_message.Message):
    __slots__ = ("token", "username", "expires_at")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    token: str
    username: str
    expires_at: int
    def __init__(self, token: _Optional[str] = ..., username: _Optional[str] = ..., expires_at: _Optional[int] = ...) -> None: ...

class ResendRequest(_message.Message):
    __slots__ = ("challenge_id",)
    CHALLENGE_ID_FIELD_NUMBER: _ClassVar[int]
    challenge_id: str
    def __init__(self, challenge_id: _Optional[str] = ...) -> None: ...

class UserRef(_message.Message):
    __slots__ = ("username",)
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    username: str
    def __init__(self, username: _Optional[str] = ...) -> None: ...

class KeyBundle(_message.Message):
    __slots__ = ("username", "identity_dh", "identity_sign", "signed_prekey", "prekey_signature", "key_id")
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    IDENTITY_DH_FIELD_NUMBER: _ClassVar[int]
    IDENTITY_SIGN_FIELD_NUMBER: _ClassVar[int]
    SIGNED_PREKEY_FIELD_NUMBER: _ClassVar[int]
    PREKEY_SIGNATURE_FIELD_NUMBER: _ClassVar[int]
    KEY_ID_FIELD_NUMBER: _ClassVar[int]
    username: str
    identity_dh: bytes
    identity_sign: bytes
    signed_prekey: bytes
    prekey_signature: bytes
    key_id: int
    def __init__(self, username: _Optional[str] = ..., identity_dh: _Optional[bytes] = ..., identity_sign: _Optional[bytes] = ..., signed_prekey: _Optional[bytes] = ..., prekey_signature: _Optional[bytes] = ..., key_id: _Optional[int] = ...) -> None: ...

class Contact(_message.Message):
    __slots__ = ("username", "state", "key_id")
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    KEY_ID_FIELD_NUMBER: _ClassVar[int]
    username: str
    state: ContactState
    key_id: int
    def __init__(self, username: _Optional[str] = ..., state: _Optional[_Union[ContactState, str]] = ..., key_id: _Optional[int] = ...) -> None: ...

class ContactList(_message.Message):
    __slots__ = ("contacts",)
    CONTACTS_FIELD_NUMBER: _ClassVar[int]
    contacts: _containers.RepeatedCompositeFieldContainer[Contact]
    def __init__(self, contacts: _Optional[_Iterable[_Union[Contact, _Mapping]]] = ...) -> None: ...

class FriendAnswer(_message.Message):
    __slots__ = ("username", "accept")
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    ACCEPT_FIELD_NUMBER: _ClassVar[int]
    username: str
    accept: bool
    def __init__(self, username: _Optional[str] = ..., accept: _Optional[bool] = ...) -> None: ...

class Envelope(_message.Message):
    __slots__ = ("id", "sender", "recipient", "kind", "header", "ciphertext", "sent_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    SENDER_FIELD_NUMBER: _ClassVar[int]
    RECIPIENT_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    HEADER_FIELD_NUMBER: _ClassVar[int]
    CIPHERTEXT_FIELD_NUMBER: _ClassVar[int]
    SENT_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    sender: str
    recipient: str
    kind: ChatKind
    header: bytes
    ciphertext: bytes
    sent_at: int
    def __init__(self, id: _Optional[int] = ..., sender: _Optional[str] = ..., recipient: _Optional[str] = ..., kind: _Optional[_Union[ChatKind, str]] = ..., header: _Optional[bytes] = ..., ciphertext: _Optional[bytes] = ..., sent_at: _Optional[int] = ...) -> None: ...

class SendReply(_message.Message):
    __slots__ = ("id", "sent_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    SENT_AT_FIELD_NUMBER: _ClassVar[int]
    id: int
    sent_at: int
    def __init__(self, id: _Optional[int] = ..., sent_at: _Optional[int] = ...) -> None: ...

class HistoryRequest(_message.Message):
    __slots__ = ("peer", "before_id", "limit")
    PEER_FIELD_NUMBER: _ClassVar[int]
    BEFORE_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    peer: str
    before_id: int
    limit: int
    def __init__(self, peer: _Optional[str] = ..., before_id: _Optional[int] = ..., limit: _Optional[int] = ...) -> None: ...

class HistoryReply(_message.Message):
    __slots__ = ("messages",)
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    messages: _containers.RepeatedCompositeFieldContainer[Envelope]
    def __init__(self, messages: _Optional[_Iterable[_Union[Envelope, _Mapping]]] = ...) -> None: ...

class AckRequest(_message.Message):
    __slots__ = ("ids",)
    IDS_FIELD_NUMBER: _ClassVar[int]
    ids: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, ids: _Optional[_Iterable[int]] = ...) -> None: ...

class Event(_message.Message):
    __slots__ = ("message", "contact")
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CONTACT_FIELD_NUMBER: _ClassVar[int]
    message: Envelope
    contact: Contact
    def __init__(self, message: _Optional[_Union[Envelope, _Mapping]] = ..., contact: _Optional[_Union[Contact, _Mapping]] = ...) -> None: ...
