"""Тонкая обёртка над gRPC: канал с TLS, токен в метаданных, понятные ошибки.

Все вызовы блокирующие — из интерфейса их запускают в фоновых потоках (ui/worker.py).
"""
import platform

import grpc

from proto import messenger_pb2 as pb
from proto import messenger_pb2_grpc as pb_grpc

from . import config

FRIENDLY = {
    grpc.StatusCode.UNAVAILABLE: "Сервер недоступен. Проверьте, что он запущен.",
    grpc.StatusCode.DEADLINE_EXCEEDED: "Сервер не ответил вовремя.",
}


class ApiError(Exception):
    def __init__(self, code: grpc.StatusCode, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class Api:
    def __init__(self, host: str = config.SERVER_HOST, port: int = config.SERVER_PORT, insecure: bool = config.INSECURE):
        target = f"{host}:{port}"
        if insecure:
            self.channel = grpc.insecure_channel(target)
        else:
            if not config.CA_FILE.exists():
                raise ApiError(grpc.StatusCode.FAILED_PRECONDITION,
                               f"Нет сертификата {config.CA_FILE}. Создайте его: python scripts/make_dev_cert.py")
            credentials = grpc.ssl_channel_credentials(root_certificates=config.CA_FILE.read_bytes())
            self.channel = grpc.secure_channel(target, credentials)
        self.auth = pb_grpc.AuthStub(self.channel)
        self.messenger = pb_grpc.MessengerStub(self.channel)
        self.token: str | None = None

    @property
    def metadata(self) -> tuple:
        return (("authorization", f"Bearer {self.token}"),) if self.token else ()

    def _call(self, rpc, request, timeout: float = 15):
        try:
            return rpc(request, metadata=self.metadata, timeout=timeout)
        except grpc.RpcError as exc:
            code = exc.code()
            raise ApiError(code, exc.details() or FRIENDLY.get(code, f"Ошибка сервера: {code.name}")) from None

    # ---------- вход ----------

    def login(self, email: str, password: str) -> pb.LoginReply:
        device = f"{platform.system()} {platform.node()}".strip()
        return self._call(self.auth.Login, pb.LoginRequest(email=email, password=password, device_name=device))

    def verify(self, challenge_id: str, code: str) -> pb.VerifyReply:
        reply = self._call(self.auth.VerifyCode, pb.VerifyRequest(challenge_id=challenge_id, code=code))
        self.token = reply.token
        return reply

    def resend(self, challenge_id: str) -> None:
        self._call(self.auth.ResendCode, pb.ResendRequest(challenge_id=challenge_id))

    def logout(self) -> None:
        try:
            self._call(self.auth.Logout, pb.Empty(), timeout=3)
        finally:
            self.token = None

    # ---------- мессенджер ----------

    def call(self, method: str, request=None):
        """api.call("ListContacts"), api.call("SendFriendRequest", pb.UserRef(username="bob"))"""
        return self._call(getattr(self.messenger, method), request if request is not None else pb.Empty())

    def subscribe(self):
        """Поток событий. Возвращает объект вызова: по нему итерируются и его можно отменить."""
        return self.messenger.Subscribe(pb.Empty(), metadata=self.metadata)

    def close(self) -> None:
        self.channel.close()
