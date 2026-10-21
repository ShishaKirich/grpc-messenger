"""Окно входа: шаг 1 — email и пароль, шаг 2 — код (почта, приложение или резервный код).

После второго фактора открывается зашифрованное хранилище ключей на устройстве.
Пароль держится в памяти только до этого момента.
"""
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from e2e.keystore import Keystore, WrongPassword
from proto import messenger_pb2 as pb

from .. import config
from ..api import Api, ApiError
from ..core import Messenger, new_keystore, open_keystore
from .worker import run_async

FEATURES = [
    ("🛡", "Вход в два шага", "Пароль и код с почты или из приложения-аутентификатора"),
    ("🔐", "Сквозное шифрование", "Сервер хранит только шифротекст и не может прочитать переписку"),
    ("🔒", "Секретные чаты", "Double Ratchet, сообщения только на устройстве, таймер удаления"),
]


def field(placeholder: str, password: bool = False) -> QLineEdit:
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    edit.setMinimumHeight(44)
    if password:
        edit.setEchoMode(QLineEdit.Password)
    return edit


def button(text: str, name: str = "") -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(44 if name == "primary" else 0)
    return b


class LoginWindow(QWidget):
    logged_in = Signal(object, bool)   # Messenger, новое ли это устройство

    def __init__(self, notice: str = ""):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Лес из Шишек — вход")
        self.resize(960, 620)
        self.api: Api | None = None
        self.challenge_id, self.method, self._password, self._email = "", 0, "", ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._brand_panel(), 5)

        right = QVBoxLayout()
        right.setContentsMargins(56, 40, 56, 40)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._credentials_page())
        self.pages.addWidget(self._code_page())
        right.addStretch(1)
        right.addWidget(self.pages)
        right.addStretch(1)
        holder = QWidget()
        holder.setLayout(right)
        root.addWidget(holder, 6)

        self.resend_timer = QTimer(self, interval=1000, timeout=self._tick)
        if notice:
            self.error.setText(notice)

    # ---------- вёрстка ----------

    def _brand_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("brand")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(48, 48, 48, 48)
        logo = QLabel("🌲")
        logo.setStyleSheet("font-size: 44pt; background: transparent;")
        name = QLabel("Лес из Шишек")
        name.setObjectName("title")
        name.setStyleSheet("background: transparent; font-size: 24pt; font-weight: 800;")
        tagline = QLabel("Мессенджер, в котором переписку не прочитает даже сервер.")
        tagline.setWordWrap(True)
        tagline.setStyleSheet("background: transparent; color: #a9c4b7; font-size: 11pt;")
        lay.addWidget(logo)
        lay.addWidget(name)
        lay.addWidget(tagline)
        lay.addSpacing(28)
        for icon, title, text in FEATURES:
            row = QHBoxLayout()
            ic = QLabel(icon)
            ic.setStyleSheet("font-size: 16pt; background: transparent;")
            ic.setFixedWidth(36)
            col = QVBoxLayout()
            t = QLabel(title)
            t.setStyleSheet("font-weight: 700; background: transparent;")
            d = QLabel(text)
            d.setWordWrap(True)
            d.setStyleSheet("color: #a9c4b7; background: transparent; font-size: 9pt;")
            col.addWidget(t)
            col.addWidget(d)
            row.addWidget(ic, 0, Qt.AlignTop)
            row.addLayout(col)
            lay.addLayout(row)
            lay.addSpacing(10)
        lay.addStretch(1)
        return panel

    def _credentials_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        title = QLabel("Вход")
        title.setObjectName("title")
        sub = QLabel("Используйте аккаунт, созданный на сайте.")
        sub.setObjectName("muted")
        self.email = field("Email")
        self.password = field("Пароль", password=True)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        self.login_btn = button("Продолжить", "primary")
        self.login_btn.clicked.connect(self._submit_credentials)
        self.password.returnPressed.connect(self._submit_credentials)
        self.email.returnPressed.connect(self.password.setFocus)

        links = QHBoxLayout()
        register, forgot = button("Создать аккаунт", "link"), button("Забыли пароль?", "link")
        register.clicked.connect(lambda: webbrowser.open(f"{config.WEB_URL}/register"))
        forgot.clicked.connect(lambda: webbrowser.open(f"{config.WEB_URL}/forgot"))
        links.addWidget(register)
        links.addStretch(1)
        links.addWidget(forgot)

        for w in (title, sub):
            lay.addWidget(w)
        lay.addSpacing(10)
        for w in (self.email, self.password, self.error, self.login_btn):
            lay.addWidget(w)
        lay.addLayout(links)
        return page

    def _code_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        back = button("←  Назад", "link")
        back.clicked.connect(self._back)
        title = QLabel("Подтвердите вход")
        title.setObjectName("title")
        self.code_hint = QLabel()
        self.code_hint.setObjectName("muted")
        self.code_hint.setWordWrap(True)
        self.code = field("••••••")
        self.code.setObjectName("code")
        self.code.setAlignment(Qt.AlignCenter)
        self.code.setMaxLength(12)
        self.code.returnPressed.connect(self._submit_code)
        self.code_error = QLabel()
        self.code_error.setObjectName("error")
        self.code_error.setWordWrap(True)
        self.verify_btn = button("Войти", "primary")
        self.verify_btn.clicked.connect(self._submit_code)
        self.resend_btn = button("Отправить код ещё раз", "link")
        self.resend_btn.clicked.connect(self._resend)
        lay.addWidget(back, 0, Qt.AlignLeft)
        lay.addWidget(title)
        lay.addWidget(self.code_hint)
        lay.addSpacing(6)
        for w in (self.code, self.code_error, self.verify_btn, self.resend_btn):
            lay.addWidget(w)
        return page

    # ---------- шаг 1 ----------

    def _submit_credentials(self):
        email, password = self.email.text().strip(), self.password.text()
        if not email or not password:
            self.error.setText("Введите email и пароль.")
            return
        try:
            self.api = self.api or Api()
        except ApiError as exc:
            self.error.setText(exc.message)
            return
        self._busy(self.login_btn, True, "Проверяем…")
        self._email, self._password = email, password
        run_async(self.api.login, email, password, on_done=self._got_challenge, on_error=self._credentials_failed)

    def _credentials_failed(self, message: str):
        self._busy(self.login_btn, False, "Продолжить")
        self.error.setText(message)

    def _got_challenge(self, reply: pb.LoginReply):
        self._busy(self.login_btn, False, "Продолжить")
        self.error.clear()
        self.challenge_id, self.method = reply.challenge_id, reply.method
        if reply.method == pb.TOTP:
            self.code_hint.setText("Откройте приложение-аутентификатор и введите шестизначный код. "
                                   "Нет телефона под рукой — подойдёт резервный код вида abcd-efgh.")
            self.resend_btn.hide()
        else:
            self.code_hint.setText(f"Мы отправили код на {mask_email(self._email)}. Он действует 5 минут.")
            self.resend_btn.show()
            self._start_cooldown()
        self.code.clear()
        self.code_error.clear()
        self.pages.setCurrentIndex(1)
        self.code.setFocus()

    # ---------- шаг 2 ----------

    def _submit_code(self):
        code = self.code.text().strip()
        if not code:
            return
        self._busy(self.verify_btn, True, "Проверяем…")
        run_async(self._finish_login, code, on_done=self._unlocked, on_error=self._code_failed)

    def _finish_login(self, code: str):
        """Фоновый поток: второй фактор, затем хранилище ключей (Argon2 — это пара сотен миллисекунд)."""
        reply = self.api.verify(self.challenge_id, code)
        try:
            store, created = open_keystore(config.KEYSTORE_DIR, reply.username, self._password)
        except WrongPassword:
            return reply.username, None, False
        return reply.username, store, created

    def _code_failed(self, message: str):
        self._busy(self.verify_btn, False, "Войти")
        self.code_error.setText(message)
        self.code.selectAll()
        if "Войдите заново" in message:
            self._back()
            self.error.setText(message)

    def _unlocked(self, result):
        username, store, created = result
        if store is None:  # хранилище есть, но пароль другой — скорее всего, его сменили на сайте
            dialog = KeystoreDialog(username, self._password, self)
            if dialog.exec() != QDialog.Accepted:
                self._busy(self.verify_btn, False, "Войти")
                self.api.logout()
                self._back()
                return
            store, created = dialog.store, dialog.created
        self._password = ""  # nosec B105 — пароль больше не нужен, стираем его из памяти
        self.password.clear()
        run_async(self._start, username, store, created, on_done=self._started, on_error=self._code_failed)

    def _start(self, username: str, store: Keystore, created: bool):
        messenger = Messenger(self.api, username, store)
        new_device = False
        if created:
            try:
                self.api.call("GetKeys", pb.UserRef(username=username))
                new_device = True   # на сервере уже были ключи с другого устройства
            except ApiError:
                pass
        messenger.publish_keys()
        messenger.refresh_contacts()
        return messenger, new_device

    def _started(self, result):
        self.resend_timer.stop()
        self.logged_in.emit(*result)

    # ---------- прочее ----------

    def _resend(self):
        self.resend_btn.setEnabled(False)
        run_async(self.api.resend, self.challenge_id,
                  on_done=lambda _: (self.code_error.setText(""), self._start_cooldown()),
                  on_error=lambda m: (self.code_error.setText(m), self.resend_btn.setEnabled(True)))

    def _start_cooldown(self):
        self._cooldown = 60
        self.resend_btn.setEnabled(False)
        self._tick()
        self.resend_timer.start()

    def _tick(self):
        self._cooldown -= 1
        if self._cooldown <= 0:
            self.resend_timer.stop()
            self.resend_btn.setEnabled(True)
            self.resend_btn.setText("Отправить код ещё раз")
        else:
            self.resend_btn.setText(f"Отправить код ещё раз через {self._cooldown} с")

    def _back(self):
        self.resend_timer.stop()
        self._busy(self.verify_btn, False, "Войти")
        self.pages.setCurrentIndex(0)
        self.password.setFocus()

    @staticmethod
    def _busy(btn: QPushButton, busy: bool, text: str):
        btn.setEnabled(not busy)
        btn.setText(text)


class KeystoreDialog(QDialog):
    """Хранилище ключей зашифровано другим паролем: вводим прежний или создаём новые ключи."""

    def __init__(self, username: str, current_password: str, parent=None):
        super().__init__(parent)
        self.username, self.current = username, current_password
        self.store, self.created = None, False
        self.setWindowTitle("Ключи шифрования")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        title = QLabel("Ключи защищены прежним паролем")
        title.setObjectName("h2")
        text = QLabel("Похоже, пароль меняли на сайте. Введите прежний пароль, чтобы открыть ключи на этом "
                      "компьютере. Они будут перешифрованы новым паролем.")
        text.setWordWrap(True)
        text.setObjectName("muted")
        self.old = field("Прежний пароль", password=True)
        self.error = QLabel()
        self.error.setObjectName("error")
        ok = button("Открыть ключи", "primary")
        ok.clicked.connect(self._open)
        self.old.returnPressed.connect(self._open)
        reset = button("Создать новые ключи", "danger")
        reset.clicked.connect(self._reset)
        for w in (title, text, self.old, self.error, ok, reset):
            lay.addWidget(w)

    def _open(self):
        try:
            store = Keystore.open(config.KEYSTORE_DIR, self.username, self.old.text())
        except WrongPassword:
            self.error.setText("Пароль не подошёл.")
            return
        store.change_password(self.current)
        self.store = store
        self.accept()

    def _reset(self):
        answer = QMessageBox.warning(
            self, "Создать новые ключи?",
            "Секретные чаты на этом компьютере пропадут, а старые сообщения обычных чатов не расшифруются. "
            "Друзья увидят, что ваш ключ изменился.", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer == QMessageBox.Yes:
            self.store, self.created = new_keystore(config.KEYSTORE_DIR, self.username, self.current), True
            self.accept()


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "•" * max(1, len(name) - 2)) + "@" + domain
