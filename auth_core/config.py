"""Настройки приложения. Читаются из переменных окружения или файла .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Общие
    app_name: str = "Лес из Шишек"
    secret_key: str = "change-me-please-to-a-long-random-string"
    database_path: str = "data/app.db"
    cookie_secure: bool = False  # True, когда сайт работает по HTTPS (включает и HSTS)

    # Почта: "console" печатает письма в терминал (для разработки), "smtp" отправляет их
    mail_backend: str = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_timeout: float = 15.0

    # Одноразовые коды
    code_length: int = 6
    code_ttl_seconds: int = 300        # код живёт 5 минут
    code_max_attempts: int = 5         # после 5 неверных вводов код сгорает
    code_resend_cooldown: int = 60     # повторная отправка не чаще раза в минуту
    codes_per_ip_per_hour: int = 20    # защита от рассылки писем с одного IP
    codes_per_user_per_hour: int = 10  # и от перебора кода через многократные запросы новых кодов

    # Защита от подбора пароля
    login_max_failures: int = 5        # неудачных входов...
    login_window_seconds: int = 900    # ...за 15 минут, после чего вход временно блокируется

    # Требования к паролю
    password_min_length: int = 10
    password_max_length: int = 128     # ограничение защищает от DoS длинными паролями
    password_min_score: int = 3        # оценка zxcvbn от 0 до 4
    hibp_enabled: bool = True          # проверять пароль по базе утечек Have I Been Pwned
    hibp_timeout: float = 3.0

    # Сеансы и устройства
    session_lifetime_hours: int = 7 * 24   # сеанс живёт не дольше недели
    session_idle_hours: int = 24           # и завершается после суток бездействия
    trusted_device_days: int = 30

    # Мессенджер (gRPC)
    grpc_host: str = "127.0.0.1"
    grpc_port: int = 50051
    tls_cert_file: str = "certs/server.crt"   # создаёт scripts/make_dev_cert.py
    tls_key_file: str = "certs/server.key"
    challenge_ttl_seconds: int = 300          # сколько ждём второй фактор после верного пароля
    message_max_bytes: int = 64 * 1024        # предел размера одного зашифрованного сообщения
    messages_per_minute: int = 60             # защита от флуда с одного аккаунта
    secret_ttl_days: int = 7                  # недоставленные сообщения секретных чатов живут не дольше недели
    web_url: str = "http://localhost:8000"    # куда клиент отправляет за регистрацией и настройками


settings = Settings()
