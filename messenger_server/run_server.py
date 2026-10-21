"""Запуск gRPC-сервера мессенджера.

    python -m messenger_server.run_server            # TLS, сертификаты из certs/
    python -m messenger_server.run_server --insecure # без TLS, только для отладки на своём компьютере

grpc.aio обслуживает тысячи одновременных подключений в одном процессе: пока один
вызов ждёт базу или почту, сервер работает с другими. Тяжёлые вычисления (Argon2)
вынесены в отдельные потоки (asyncio.to_thread в auth_core/security.py).
"""
import argparse
import asyncio
import contextlib
import logging
import time
from pathlib import Path

import grpc

from auth_core.config import settings
from auth_core.db import init_db, opened
from proto import messenger_pb2 as pb
from proto import messenger_pb2_grpc as pb_grpc

from .auth_service import AuthService
from .hub import Hub
from .messenger_service import MessengerService

log = logging.getLogger("server")
SCHEMA_FILE = Path(__file__).with_name("schema.sql")


async def cleanup_once() -> None:
    """Удаляет просроченные вызовы входа и недоставленные сообщения секретных чатов."""
    now = int(time.time())
    async with opened() as db:
        await db.execute("DELETE FROM login_challenges WHERE expires_at < ?", (now - 3600,))
        await db.execute("DELETE FROM messages WHERE kind = ? AND sent_at < ?",
                         (pb.SECRET, now - settings.secret_ttl_days * 86400))


async def periodic_cleanup() -> None:
    while True:
        with contextlib.suppress(Exception):
            await cleanup_once()
        await asyncio.sleep(3600)


def build_server(insecure: bool = False, address: str | None = None) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server(options=[
        ("grpc.max_receive_message_length", settings.message_max_bytes + 16 * 1024),
        ("grpc.keepalive_time_ms", 30_000),
    ])
    pb_grpc.add_AuthServicer_to_server(AuthService(), server)
    pb_grpc.add_MessengerServicer_to_server(MessengerService(Hub()), server)
    address = address or f"{settings.grpc_host}:{settings.grpc_port}"
    if insecure:
        port = server.add_insecure_port(address)
    else:
        cert, key = Path(settings.tls_cert_file), Path(settings.tls_key_file)
        if not cert.exists() or not key.exists():
            raise SystemExit(f"Нет сертификата {cert}. Создайте его: python scripts/make_dev_cert.py")
        credentials = grpc.ssl_server_credentials([(key.read_bytes(), cert.read_bytes())])
        port = server.add_secure_port(address, credentials)
    return server, port


async def main(insecure: bool) -> None:
    if settings.mail_backend == "smtp" and settings.secret_key.startswith("change-me"):
        raise SystemExit("Задайте SECRET_KEY в .env перед запуском с настоящей почтой.")
    await init_db(SCHEMA_FILE)
    server, port = build_server(insecure)
    await server.start()
    cleanup = asyncio.create_task(periodic_cleanup())
    mode = "БЕЗ TLS (только для отладки!)" if insecure else "TLS"
    log.warning("Сервер мессенджера запущен на %s:%s, %s. Остановить: Ctrl+C", settings.grpc_host, port, mode)
    try:
        await server.wait_for_termination()
    finally:
        cleanup.cancel()
        await server.stop(grace=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="gRPC-сервер мессенджера «Лес из Шишек»")
    parser.add_argument("--insecure", action="store_true", help="без TLS (только для локальной отладки)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main(args.insecure))
