"""Главное окно: список чатов слева, переписка справа."""
import time
import webbrowser

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from proto import messenger_pb2 as pb

from .. import config
from ..core import SECRET_TTL_CHOICES, TEXT_MAX, ChatMessage, Messenger, Update
from . import theme
from .widgets import Avatar, Bubble, ChatRow, DayLine, SystemLine, Toast
from .worker import EventStream, run_async

REGULAR, SECRET = "regular", "secret"


class Composer(QPlainTextEdit):
    """Поле ввода: Enter — отправить, Shift+Enter — новая строка."""
    submitted = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    logged_out = Signal(str)

    def __init__(self, messenger: Messenger, new_device: bool = False):
        super().__init__()
        self.m = messenger
        self.current: tuple[str, str] | None = None
        self.history: dict[str, list[ChatMessage]] = {}     # обычные чаты, уже загруженные с сервера
        self.unread: dict[tuple[str, str], int] = {}
        self.preview: dict[tuple[str, str], str] = {}
        self._closing = False

        self.setWindowTitle(f"Лес из Шишек — {messenger.me}")
        self.resize(1120, 720)
        self.setMinimumSize(820, 520)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._sidebar())
        self.right = QStackedWidget()
        self.right.addWidget(self._empty_state())
        self.right.addWidget(self._chat_panel())
        layout.addWidget(self.right, 1)
        self.toast = Toast(root)

        self.stream = EventStream(messenger)
        self.stream.updates.connect(self._on_updates)
        self.stream.online.connect(self._on_online)
        self.stream.session_lost.connect(self._on_session_lost)
        self.stream.start()

        self.ticker = QTimer(self, interval=1000, timeout=self._purge_expired)
        self.ticker.start()
        self.rebuild_list()
        if new_device:
            QTimer.singleShot(400, lambda: self.toast.show_text(
                "Это новое устройство: ключи шифрования созданы заново. Друзья увидят, что ваш ключ изменился, "
                "старые сообщения на этом компьютере не расшифруются.", 8000))

    # ---------- боковая панель ----------

    def _sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(330)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 14, 0, 10)
        lay.setSpacing(8)

        me = QHBoxLayout()
        me.setContentsMargins(16, 0, 10, 0)
        me.addWidget(Avatar(self.m.me, 40))
        names = QVBoxLayout()
        names.setSpacing(0)
        title = QLabel(self.m.me)
        title.setStyleSheet("font-weight: 700; font-size: 11pt;")
        self.status = QLabel("● подключение…")
        self.status.setObjectName("small")
        names.addWidget(title)
        names.addWidget(self.status)
        me.addLayout(names, 1)
        menu_btn = QPushButton("⋯")
        menu_btn.setObjectName("icon")
        menu_btn.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self)
        menu.addAction("Личный кабинет на сайте", lambda: webbrowser.open(f"{config.WEB_URL}/dashboard"))
        menu.addAction("Настройки безопасности (2FA)", lambda: webbrowser.open(f"{config.WEB_URL}/settings"))
        menu.addSeparator()
        menu.addAction("Выйти", self.logout)
        menu_btn.setMenu(menu)
        menu_btn.setStyleSheet("QPushButton::menu-indicator { width: 0; }")
        me.addWidget(menu_btn)
        lay.addLayout(me)

        add = QHBoxLayout()
        add.setContentsMargins(14, 6, 14, 2)
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("Добавить друга по имени пользователя")
        self.add_input.returnPressed.connect(self.add_friend)
        add_btn = QPushButton("+")
        add_btn.setObjectName("primary")
        add_btn.setFixedWidth(44)
        add_btn.setMinimumHeight(40)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.add_friend)
        add.addWidget(self.add_input)
        add.addWidget(add_btn)
        lay.addLayout(add)

        self.list = QListWidget()
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._item_clicked)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        lay.addWidget(self.list, 1)
        return side

    def rebuild_list(self):
        contacts = self.m.contacts
        groups = [
            ("ЗАЯВКИ В ДРУЗЬЯ", [p for p, s in contacts.items() if s == pb.INCOMING], "request"),
            ("СЕКРЕТНЫЕ ЧАТЫ", self.m.secret_peers(), SECRET),
            ("ЧАТЫ", [p for p, s in contacts.items() if s == pb.FRIEND], REGULAR),
            ("ОТПРАВЛЕННЫЕ ЗАЯВКИ", [p for p, s in contacts.items() if s == pb.OUTGOING], "outgoing"),
            ("ЗАБЛОКИРОВАНЫ", [p for p, s in contacts.items() if s == pb.BLOCKED], "blocked"),
        ]
        self.list.clear()
        for header, peers, kind in groups:
            if not peers:
                continue
            self._add_section(header)
            for peer in sorted(peers, key=str.lower):
                self._add_row(kind, peer)
        if self.list.count() == 0:
            self._add_section("ПОКА НИКОГО НЕТ")
            hint = QListWidgetItem()
            hint.setFlags(Qt.NoItemFlags)
            label = QLabel("Добавьте друга по имени пользователя — после того как он примет заявку, "
                           "можно переписываться.")
            label.setWordWrap(True)
            label.setObjectName("muted")
            label.setContentsMargins(18, 4, 18, 4)
            hint.setSizeHint(QSize(300, 64))
            self.list.addItem(hint)
            self.list.setItemWidget(hint, label)

    def _add_section(self, text: str):
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        label = QLabel(text)
        label.setObjectName("section")
        item.setSizeHint(label.sizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, label)

    def _add_row(self, kind: str, peer: str):
        key = (kind, peer)
        subtitles = {
            "request": "хочет добавить вас в друзья",
            SECRET: "🔒 секретный чат",
            REGULAR: "🔐 сквозное шифрование",
            "outgoing": "ждёт ответа",
            "blocked": "заблокирован",
        }
        subtitle = self.preview.get(key) or subtitles[kind]
        row = ChatRow(peer, subtitle, secret=kind == SECRET, unread=self.unread.get(key, 0),
                      request=kind == "request", dimmed=kind in ("outgoing", "blocked"))
        if kind == "request":
            row.accepted.connect(lambda p=peer: self._answer(p, True))
            row.declined.connect(lambda p=peer: self._answer(p, False))
        item = QListWidgetItem()
        item.setData(Qt.UserRole, key)
        item.setSizeHint(row.sizeHint())
        if kind not in (REGULAR, SECRET):
            item.setFlags(Qt.ItemIsEnabled)
        self.list.addItem(item)
        self.list.setItemWidget(item, row)
        if self.current == key:
            item.setSelected(True)

    def _item_clicked(self, item: QListWidgetItem):
        key = item.data(Qt.UserRole)
        if key and key[0] in (REGULAR, SECRET):
            self.open_chat(*key)

    def _list_menu(self, pos):
        item = self.list.itemAt(pos)
        key = item.data(Qt.UserRole) if item else None
        if not key:
            return
        kind, peer = key
        menu = QMenu(self)
        if kind == REGULAR:
            menu.addAction("Удалить из друзей", lambda: self._contact("RemoveFriend", peer, "Удалён из друзей"))
            menu.addAction("Заблокировать", lambda: self._contact("Block", peer, "Пользователь заблокирован"))
        elif kind == "outgoing":
            menu.addAction("Отменить заявку", lambda: self._contact("RemoveFriend", peer, "Заявка отменена"))
        elif kind == "blocked":
            menu.addAction("Разблокировать", lambda: self._contact("Unblock", peer, "Пользователь разблокирован"))
        elif kind == SECRET:
            menu.addAction("Закрыть секретный чат", lambda: self.close_secret(peer))
        menu.exec(self.list.mapToGlobal(pos))

    # ---------- правая часть ----------

    def _empty_state(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        icon = QLabel("🌲")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 54pt;")
        title = QLabel("Выберите чат")
        title.setObjectName("h2")
        title.setAlignment(Qt.AlignCenter)
        text = QLabel("Сообщения шифруются на вашем устройстве. Сервер хранит только шифротекст,\n"
                      "а секретные чаты вообще не покидают ваш компьютер.")
        text.setObjectName("muted")
        text.setAlignment(Qt.AlignCenter)
        for w in (icon, title, text):
            lay.addWidget(w)
        lay.addStretch(1)
        return page

    def _chat_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QFrame()
        header.setObjectName("chatHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 12, 10)
        self.header_avatar = QHBoxLayout()
        h.addLayout(self.header_avatar)
        names = QVBoxLayout()
        names.setSpacing(1)
        self.chat_title = QLabel()
        self.chat_title.setStyleSheet("font-weight: 700; font-size: 12pt;")
        self.chat_sub = QLabel()
        self.chat_sub.setObjectName("small")
        names.addWidget(self.chat_title)
        names.addWidget(self.chat_sub)
        h.addLayout(names, 1)

        self.ttl_box = QComboBox()
        for seconds, label in SECRET_TTL_CHOICES.items():
            self.ttl_box.addItem(f"⏱ {label}", seconds)
        self.ttl_box.setToolTip("Таймер самоуничтожения: сообщение исчезнет у обоих после прочтения")
        self.ttl_box.activated.connect(self._ttl_changed)
        self.secret_btn = QPushButton("🔒  Секретный чат")
        self.secret_btn.setObjectName("secret")
        self.secret_btn.setCursor(Qt.PointingHandCursor)
        self.secret_btn.clicked.connect(self._secret_clicked)
        self.verify_btn = QPushButton("Код безопасности")
        self.verify_btn.setCursor(Qt.PointingHandCursor)
        self.verify_btn.clicked.connect(self.show_safety_number)
        self.chat_menu_btn = QPushButton("⋯")
        self.chat_menu_btn.setObjectName("icon")
        self.chat_menu_btn.setCursor(Qt.PointingHandCursor)
        self.chat_menu_btn.setStyleSheet("QPushButton::menu-indicator { width: 0; }")
        for w in (self.ttl_box, self.secret_btn, self.verify_btn, self.chat_menu_btn):
            h.addWidget(w)
        lay.addWidget(header)

        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        banner_box = QHBoxLayout()
        banner_box.setContentsMargins(16, 10, 16, 0)
        banner_box.addWidget(self.banner)
        lay.addLayout(banner_box)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.feed_widget = QWidget()
        self.feed = QVBoxLayout(self.feed_widget)
        self.feed.setContentsMargins(0, 12, 0, 12)
        self.feed.setSpacing(2)
        self.feed.addStretch(1)
        self.scroll.setWidget(self.feed_widget)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._stick_to_bottom)
        lay.addWidget(self.scroll, 1)

        composer = QFrame()
        composer.setObjectName("composer")
        c = QHBoxLayout(composer)
        c.setContentsMargins(16, 12, 16, 12)
        c.setSpacing(10)
        self.input = Composer()
        self.input.setPlaceholderText("Сообщение…")
        self.input.setFixedHeight(46)
        self.input.submitted.connect(self.send)
        self.input.textChanged.connect(self._resize_input)
        send = QPushButton("➤")
        send.setObjectName("send")
        send.setCursor(Qt.PointingHandCursor)
        send.setToolTip("Отправить (Enter)")
        send.clicked.connect(self.send)
        c.addWidget(self.input, 1)
        c.addWidget(send, 0, Qt.AlignBottom)
        lay.addWidget(composer)
        return panel

    # ---------- открытие чата ----------

    def open_chat(self, kind: str, peer: str):
        self.current = (kind, peer)
        self.unread.pop(self.current, None)
        self.right.setCurrentIndex(1)
        secret = kind == SECRET

        while self.header_avatar.count():
            self.header_avatar.takeAt(0).widget().deleteLater()
        self.header_avatar.addWidget(Avatar(peer, 40, secret))
        self.chat_title.setText(peer)
        self.chat_title.setStyleSheet(f"font-weight: 700; font-size: 12pt; color: {theme.AMBER if secret else theme.TEXT};")
        self.ttl_box.setVisible(secret)
        if secret:
            self.ttl_box.setCurrentIndex(max(0, self.ttl_box.findData(self.m.secret_ttl(peer))))
        self.secret_btn.setText("Обычный чат" if secret else
                                ("🔒  Открыть секретный" if peer in self.m.secret_peers() else "🔒  Секретный чат"))
        self.input.setPlaceholderText("Секретное сообщение…" if secret else "Сообщение…")

        menu = QMenu(self)
        if secret:
            menu.addAction("Закрыть секретный чат", lambda: self.close_secret(peer))
        else:
            menu.addAction("Удалить из друзей", lambda: self._contact("RemoveFriend", peer, "Удалён из друзей"))
            menu.addAction("Заблокировать", lambda: self._contact("Block", peer, "Пользователь заблокирован"))
        self.chat_menu_btn.setMenu(menu)

        self._update_subtitle()
        self.banner.hide()
        self.rebuild_list()
        if secret:
            self.m.mark_read(peer)
            self.render(self.m.secret_messages(peer))
        elif peer in self.history:
            self.render(self.history[peer])
        else:
            self.render([])
            run_async(self.m.history, peer, on_done=lambda msgs, p=peer: self._history_loaded(p, msgs),
                      on_error=self.toast.show_text)
        # ключи собеседника: нужны для кода безопасности и предупреждения о смене ключа
        run_async(self.m.bundle, peer, True, on_done=lambda _: self._update_subtitle(), on_error=lambda _: None)
        self.input.setFocus()

    def _history_loaded(self, peer: str, messages: list[ChatMessage]):
        self.history[peer] = messages
        if messages:
            self.preview[(REGULAR, peer)] = short(messages[-1])
        if self.current == (REGULAR, peer):
            self.render(messages)

    def _update_subtitle(self):
        if not self.current:
            return
        kind, peer = self.current
        verified = self.m.is_verified(peer)
        mark = "ключ проверен ✓" if verified else "ключ не проверен"
        if kind == SECRET:
            self.chat_sub.setText(f"🔒 Секретный чат · Double Ratchet · {mark}")
        else:
            self.chat_sub.setText(f"🔐 Сквозное шифрование · {mark}")
        if self.m.key_history(peer) > 1 and not verified:
            self.banner.setText(f"⚠  Ключ шифрования {peer} изменился (новое устройство или переустановка). "
                                "Сверьте код безопасности, прежде чем писать что-то важное.")
            self.banner.show()

    def render(self, messages: list[ChatMessage]):
        while self.feed.count() > 1:
            item = self.feed.takeAt(1)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        last_day = None
        for message in messages:
            day = time.strftime("%Y%m%d", time.localtime(message.sent_at))
            if day != last_day and not message.system:
                self.feed.addWidget(DayLine(message.sent_at))
                last_day = day
            self._add_bubble(message)

    def _add_bubble(self, message: ChatMessage):
        if message.system:
            self.feed.addWidget(SystemLine(message.text))
        else:
            self.feed.addWidget(Bubble(message.text, message.sent_at, message.outgoing, message.secret,
                                       message.ttl, message.error))

    def _stick_to_bottom(self, _min, maximum):
        self.scroll.verticalScrollBar().setValue(maximum)

    def _resize_input(self):
        lines = min(6, max(1, int(self.input.document().size().height())))
        self.input.setFixedHeight(28 + lines * 18)

    # ---------- действия ----------

    def send(self):
        if not self.current:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        if len(text) > TEXT_MAX:
            self.toast.show_text(f"Слишком длинное сообщение: не больше {TEXT_MAX} символов.")
            return
        kind, peer = self.current
        self.input.clear()
        fn = self.m.send_secret if kind == SECRET else self.m.send_text
        run_async(fn, peer, text, on_done=self._sent,
                  on_error=lambda msg, t=text: (self.toast.show_text(msg), self.input.setPlainText(t)))

    def _sent(self, message: ChatMessage):
        key = (SECRET if message.secret else REGULAR, message.peer)
        if not message.secret:
            history = self.history.setdefault(message.peer, [])
            if any(m.id == message.id for m in history):  # уже пришло эхом через поток событий
                return
            history.append(message)
        self.preview[key] = short(message)
        if self.current == key:
            self._add_bubble(message)

    def add_friend(self):
        name = self.add_input.text().strip()
        if not name:
            return
        self._contact("SendFriendRequest", name, f"Заявка отправлена: {name}")
        self.add_input.clear()

    def _answer(self, peer: str, accept: bool):
        run_async(self.m.contact_action, "answer", peer, accept,
                  on_done=lambda _: self.toast.show_text(f"{peer} теперь ваш друг" if accept else "Заявка отклонена"),
                  on_error=self.toast.show_text)

    def _contact(self, action: str, peer: str, done_text: str):
        def after(_):
            self.toast.show_text(done_text)
            if action in ("RemoveFriend", "Block") and self.current and self.current[1] == peer:
                self.current = None
                self.right.setCurrentIndex(0)
            run_async(self.m.refresh_contacts, on_done=lambda _: self.rebuild_list())
        run_async(self.m.contact_action, action, peer, on_done=after, on_error=self.toast.show_text)

    def _secret_clicked(self):
        kind, peer = self.current
        if kind == SECRET:
            self.open_chat(REGULAR, peer)
        elif peer in self.m.secret_peers():
            self.open_chat(SECRET, peer)
        else:
            answer = QMessageBox.question(
                self, "Секретный чат",
                f"Начать секретный чат с {peer}?\n\n"
                "• ключи создаются заново для каждого сообщения (Double Ratchet)\n"
                "• сообщения хранятся только на этом компьютере, сервер стирает их после доставки\n"
                "• можно включить таймер самоуничтожения")
            if answer == QMessageBox.Yes:
                run_async(self.m.start_secret, peer, on_done=lambda _: self.open_chat(SECRET, peer),
                          on_error=self.toast.show_text)

    def close_secret(self, peer: str):
        answer = QMessageBox.question(self, "Закрыть секретный чат",
                                      f"Переписка с {peer} будет удалена с обоих устройств без возможности "
                                      "восстановления. Продолжить?")
        if answer != QMessageBox.Yes:
            return

        def after(_):
            if self.current == (SECRET, peer):
                self.open_chat(REGULAR, peer)
            self.rebuild_list()
        run_async(self.m.close_secret, peer, on_done=after, on_error=self.toast.show_text)

    def _ttl_changed(self):
        if self.current and self.current[0] == SECRET:
            self.m.set_secret_ttl(self.current[1], self.ttl_box.currentData())

    def show_safety_number(self):
        peer = self.current[1]
        run_async(self.m.safety_number, peer, on_done=lambda n: self._safety_dialog(peer, n),
                  on_error=self.toast.show_text)

    def _safety_dialog(self, peer: str, number: str):
        dialog = SafetyDialog(peer, number, self.m.is_verified(peer), self)
        if dialog.exec() == QDialog.Accepted:
            run_async(self.m.set_verified, peer, on_done=lambda _: (self._update_subtitle(), self.banner.hide(),
                                                                     self.toast.show_text("Ключ отмечен как проверенный")))

    def logout(self):
        self._closing = True
        self.stream.stop()
        run_async(self.m.api.logout, on_done=lambda _: self.logged_out.emit(""),
                  on_error=lambda _: self.logged_out.emit(""))

    # ---------- события ----------

    def _on_updates(self, updates: list[Update]):
        rebuild = False
        for u in updates:
            if u.kind == "message":
                msg = u.message
                key = (SECRET if msg.secret else REGULAR, u.peer)
                if not msg.secret:
                    history = self.history.get(u.peer)
                    if history is not None:
                        if any(m.id == msg.id for m in history):
                            continue
                        history.append(msg)
                self.preview[key] = short(msg)
                if self.current == key and self.isActiveWindow():
                    self._add_bubble(msg)
                    if msg.secret:
                        self.m.mark_read(u.peer)
                else:
                    if self.current == key:
                        self._add_bubble(msg)
                    if not msg.outgoing:
                        self.unread[key] = self.unread.get(key, 0) + 1
                rebuild = True
            elif u.kind == "contacts":
                rebuild = True
            elif u.kind == "key_changed":
                self.toast.show_text(f"У {u.peer} новый ключ шифрования. Сверьте код безопасности.", 6000)
                if self.current and self.current[1] == u.peer:
                    run_async(self.m.bundle, u.peer, True, on_done=lambda _: self._update_subtitle())
            elif u.kind == "secret_started":
                self.toast.show_text(f"{u.peer} начал(а) с вами секретный чат 🔒", 5000)
                rebuild = True
            elif u.kind == "secret_closed":
                self.toast.show_text(f"Секретный чат с {u.peer} закрыт и удалён.", 5000)
                if self.current == (SECRET, u.peer):
                    self.open_chat(REGULAR, u.peer)
                rebuild = True
        if rebuild:
            self.rebuild_list()

    def _on_online(self, online: bool):
        self.status.setText("● в сети" if online else "● нет связи, переподключаемся…")
        self.status.setStyleSheet(f"color: {theme.ACCENT if online else theme.DANGER}; font-size: 8.5pt;")
        if online:  # после переподключения могли прийти заявки и сообщения
            run_async(self.m.refresh_contacts, on_done=lambda _: self.rebuild_list(), on_error=lambda _: None)

    def _on_session_lost(self, reason: str):
        if not self._closing:
            self._closing = True
            self.logged_out.emit(reason)

    def _purge_expired(self):
        touched = self.m.purge_expired()
        if self.current and self.current[0] == SECRET and self.current[1] in touched:
            self.render(self.m.secret_messages(self.current[1]))

    def closeEvent(self, event):
        self._closing = True
        self.stream.stop()
        super().closeEvent(event)


class SafetyDialog(QDialog):
    def __init__(self, peer: str, number: str, verified: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Код безопасности")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        title = QLabel(f"Код безопасности с {peer}")
        title.setObjectName("h2")
        groups = number.split()
        rows = "\n".join(" ".join(groups[i:i + 4]) for i in range(0, 12, 4))
        digits = QLabel(rows)
        digits.setObjectName("safety")
        digits.setAlignment(Qt.AlignCenter)
        digits.setTextInteractionFlags(Qt.TextSelectableByMouse)
        digits.setStyleSheet(f"background: {theme.SURFACE_2}; border-radius: 12px; padding: 18px;")
        text = QLabel("Сравните эти цифры с теми, что видит собеседник у себя (лично или по телефону). "
                      "Если совпали — ваши сообщения никто не перехватывает, даже сервер. "
                      "Если нет — кто-то подменил ключи.")
        text.setWordWrap(True)
        text.setObjectName("muted")
        state = QLabel("✓ Вы уже отметили этот ключ как проверенный" if verified else "Ключ ещё не проверен")
        state.setStyleSheet(f"color: {theme.ACCENT if verified else theme.AMBER};")
        buttons = QHBoxLayout()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        ok = QPushButton("Цифры совпадают")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        ok.setEnabled(not verified)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(ok)
        for w in (title, digits, text, state):
            lay.addWidget(w)
        lay.addLayout(buttons)


def short(message: ChatMessage) -> str:
    text = message.text.replace("\n", " ")
    prefix = "Вы: " if message.outgoing else ""
    return (prefix + text)[:42] + ("…" if len(prefix + text) > 42 else "")
