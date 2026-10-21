"""Отправка писем: коды подтверждения и уведомления о событиях безопасности."""
import asyncio
import html
import logging
from email.message import EmailMessage

import aiosmtplib

from .config import settings

log = logging.getLogger("mailer")

CODE_SUBJECTS = {
    "verify_email": "Подтверждение регистрации",
    "login": "Код для входа",
    "messenger_login": "Код для входа в мессенджер",
    "reset": "Восстановление пароля",
    "change_password": "Подтверждение смены пароля",  # nosec B105 — это тема письма, а не пароль
    "change_email": "Подтверждение нового email",
}


def _wrap_html(title: str, body_html: str) -> str:
    return f"""\
<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px;
            border-radius:12px;background:#0f172a;color:#e2e8f0">
  <h2 style="margin:0 0 8px;color:#a5b4fc">{html.escape(settings.app_name)}</h2>
  <p style="margin:0 0 20px;font-weight:bold">{html.escape(title)}</p>
  {body_html}
</div>"""


def _message(to: str, subject: str, text: str, body_html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"{settings.app_name}: {subject}"
    msg["From"] = f"{settings.app_name} <{settings.smtp_from or settings.smtp_username}>"
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(_wrap_html(subject, body_html), subtype="html")
    return msg


async def _send(msg: EmailMessage) -> None:
    if settings.mail_backend == "console":
        log.warning("[DEV] Письмо для %s: %s\n%s", msg["To"], msg["Subject"], msg.get_body(("plain",)).get_content())
        return
    await aiosmtplib.send(
        msg,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        start_tls=settings.smtp_port == 587,
        use_tls=settings.smtp_port == 465,
        timeout=settings.smtp_timeout,
    )


async def send_code(to: str, code: str, purpose: str) -> None:
    """Отправляет код. Бросает исключение, если письмо не ушло."""
    minutes = settings.code_ttl_seconds // 60
    subject = CODE_SUBJECTS[purpose]
    if settings.mail_backend == "console":
        # Отдельная строка с кодом удобна при разработке и в нагрузочных тестах
        log.warning("[DEV] Код для %s (%s): %s", to, purpose, code)
        return
    text = (f"Ваш код: {code}\n\nКод действует {minutes} мин. Никому его не сообщайте. "
            "Если вы не запрашивали код, просто проигнорируйте это письмо.")
    body = f"""\
  <div style="font-size:34px;letter-spacing:10px;font-weight:bold;text-align:center;
              padding:16px;border-radius:8px;background:#1e293b;color:#fff">{code}</div>
  <p style="font-size:13px;color:#94a3b8;margin-top:20px">
    Код действует {minutes} мин. Никому его не сообщайте. Если вы не запрашивали код, просто проигнорируйте письмо.
  </p>"""
    await _send(_message(to, f"{subject} — {code}", text, body))


async def send_notice(to: str, subject: str, lines: list[str]) -> None:
    """Уведомление о событии безопасности. Строки экранируются: в них бывают данные от клиента."""
    text = "\n".join(lines)
    body = "".join(f'<p style="margin:0 0 10px">{html.escape(line)}</p>' for line in lines)
    await _send(_message(to, subject, text, body))


async def send_in_background(coro) -> None:
    """Для фоновых уведомлений: ошибка отправки пишется в лог и не ломает ответ пользователю."""
    try:
        await asyncio.wait_for(coro, timeout=settings.smtp_timeout + 5)
    except Exception:
        log.exception("Не удалось отправить фоновое письмо")
