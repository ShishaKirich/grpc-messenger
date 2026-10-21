"""Общие настройки тестов: отдельная база, письма не отправляются, HIBP выключен."""
import os

os.environ.setdefault("DATABASE_PATH", "data/test.db")
os.environ.setdefault("MAIL_BACKEND", "console")
os.environ.setdefault("CODE_RESEND_COOLDOWN", "0")
os.environ.setdefault("HIBP_ENABLED", "false")
