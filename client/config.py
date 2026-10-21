"""Настройки клиента. Меняются переменными окружения, по умолчанию — локальный сервер."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SERVER_HOST = os.environ.get("MESSENGER_HOST", "localhost")
SERVER_PORT = int(os.environ.get("MESSENGER_PORT", "50051"))
# Клиент доверяет только этому центру сертификации, а не всем CA в системе
CA_FILE = Path(os.environ.get("MESSENGER_CA", ROOT / "certs" / "ca.crt"))
INSECURE = os.environ.get("MESSENGER_INSECURE", "") == "1"   # только для отладки
WEB_URL = os.environ.get("WEB_URL", "http://localhost:8000")
# Здесь лежат зашифрованные хранилища ключей (по файлу на пользователя)
KEYSTORE_DIR = Path(os.environ.get("MESSENGER_KEYSTORE", Path.home() / ".les_iz_shishek" / "keystore"))
