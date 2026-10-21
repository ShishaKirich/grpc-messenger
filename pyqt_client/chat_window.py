# chat_window.py - Основное окно чата
import sys
import os
import traceback
from datetime import datetime, timezone, timedelta

# Добавляем путь для импортов из pyqt_client
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QListWidget, QLabel,
    QListWidgetItem, QMenuBar, QStatusBar,
    QFrame, QMessageBox, QTextBrowser
)
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QAction, QColor, QPalette, QKeyEvent

# Прямые импорты из файлов в той же директории
from database_manager import DatabaseManager
from message_receiver import MessageReceiver
from dialogs import (
    AddFriendDialog, FriendRequestDialog,
    BlockUserDialog, BlacklistDialog
)
from friends_manager import FriendsManager
from block_manager import BlockManager
from message_manager import MessageManager
from ui_builder import UIBuilder



class ChatWindow(QMainWindow):
    """Главное окно чата"""

    def __init__(self, grpc_client, username):
        super().__init__()
        self.grpc_client = grpc_client
        self.username = username
        self.current_chat = None
        self.current_chat_type = None
        self._initialized = False

        # Инициализация базы данных
        self.db = DatabaseManager()

        # Словарь для хранения открытых чатов
        self._open_chats = set()

        # Для предотвращения дублирования сообщений
        self._last_displayed_messages = {}
        self._message_check_timer = None
        self._friends_check_timer = None

        # Загрузка данных
        try:
            self.friends_manager = FriendsManager(self)
            self.block_manager = BlockManager(self)
            self.message_manager = MessageManager(self)
            self.ui_builder = UIBuilder()

            self.friends = self.friends_manager.load_friends()
            self.blocked_users = {}
            self.blocked_by_users = {}
            blocked_data = self.friends_manager.load_blocked_users()
            if isinstance(blocked_data, tuple) and len(blocked_data) == 2:
                self.blocked_users, self.blocked_by_users = blocked_data
            else:
                self.blocked_users = {}
                self.blocked_by_users = {}

            self.pending_requests = self.friends_manager.load_pending_requests()
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")
            traceback.print_exc()
            self.friends = []
            self.blocked_users = {}
            self.blocked_by_users = {}
            self.pending_requests = {}

        try:
            self.ui_builder.setup_dark_theme(self)
            self.init_ui()

            if hasattr(self.grpc_client, 'set_message_callback'):
                self.grpc_client.set_message_callback(self._on_message_notification)

            self.setWindowTitle(f"Лес из Шишек - {username}")
            self.setMinimumSize(900, 600)
            self.resize(1200, 700)

            # Запускаем receiver
            self.setup_message_receiver()

            # Запускаем таймеры
            self.start_message_check_timer()
            self.start_friends_check_timer()

            # Проверяем входящие запросы
            QTimer.singleShot(1000, self.check_pending_requests)

            self._initialized = True
            print(f"✓ Окно чата инициализировано для {username}")

        except Exception as e:
            print(f"✗ Ошибка инициализации окна чата: {e}")
            traceback.print_exc()
            raise

    def init_ui(self):
        """Инициализация интерфейса"""
        try:
            central_widget = QWidget()
            self.setCentralWidget(central_widget)

            main_layout = QHBoxLayout(central_widget)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)

            # Левая панель
            left_panel = self.ui_builder.create_left_panel(self)
            main_layout.addWidget(left_panel)

            # Правая панель
            right_panel = self.ui_builder.create_right_panel(self)
            main_layout.addWidget(right_panel, 3)

            # Создаем меню
            self.ui_builder.create_menu(self)

            # Создаем статус бар
            self.status_bar = QStatusBar()
            self.status_bar.setStyleSheet("""
                QStatusBar {
                    background-color: #252526;
                    color: #A0A0A0;
                    border-top: 1px solid #3E3E42;
                    font-size: 11px;
                }
            """)
            self.setStatusBar(self.status_bar)

            # Показываем статус
            if self.blocked_by_users:
                blockers = ", ".join(self.blocked_by_users.keys())
                self.status_bar.showMessage(f"Вас заблокировали: {blockers}")
            elif self.pending_requests:
                self.status_bar.showMessage(f"У вас {len(self.pending_requests)} входящих запросов в друзья")
            else:
                self.status_bar.showMessage(f"Вы вошли как: {self.username}")

        except Exception as e:
            print(f"Ошибка инициализации UI: {e}")
            traceback.print_exc()
            raise

    def setup_message_receiver(self):
        """Настройка получения сообщений"""
        try:
            print(f"🚀 Настройка MessageReceiver для {self.username}")
            self.message_receiver = MessageReceiver(self.grpc_client, self.username)
            self.message_receiver.message_received.connect(self.handle_incoming_message)
            self.message_receiver.friend_request_received.connect(self.handle_friend_request)
            self.message_receiver.friend_request_sent.connect(self.handle_friend_request_sent)
            self.message_receiver.friend_accepted.connect(self.handle_friend_accepted)
            self.message_receiver.friend_rejected.connect(self.handle_friend_rejected)
            self.message_receiver.friend_info.connect(self.handle_friend_info)
            self.message_receiver.user_blocked.connect(self.handle_user_blocked)
            self.message_receiver.user_unblocked.connect(self.handle_user_unblocked)
            self.message_receiver.connection_error.connect(self.show_connection_error)
            self.message_receiver.start()
            print("✓ MessageReceiver запущен и подключен")
        except Exception as e:
            print(f"✗ Ошибка запуска MessageReceiver: {e}")
            traceback.print_exc()
            QMessageBox.warning(self, "Ошибка",
                                f"Не удалось запустить получение сообщений: {str(e)}")

    def start_message_check_timer(self):
        """Запуск таймера для проверки новых сообщений"""
        self._message_check_timer = QTimer()
        self._message_check_timer.timeout.connect(self.check_for_new_messages)
        self._message_check_timer.start(1000)

    def start_friends_check_timer(self):
        """Запуск таймера для проверки обновлений списка друзей"""
        self._friends_check_timer = QTimer()
        self._friends_check_timer.timeout.connect(self.check_friends_updates)
        self._friends_check_timer.start(2000)

    def check_for_new_messages(self):
        """Проверка новых сообщений в текущем чате"""
        if self.current_chat and self.current_chat_type == "personal":
            chat_id = self.get_chat_id(self.current_chat, "personal")
            self.refresh_chat_if_needed(chat_id)

    def check_friends_updates(self):
        """Проверка обновлений в списке друзей"""
        try:
            new_friends = self.friends_manager.load_friends()
            new_pending = self.friends_manager.load_pending_requests()

            if (set(new_friends) != set(self.friends) or
                    set(new_pending.keys()) != set(self.pending_requests.keys())):
                self.friends = new_friends
                self.pending_requests = new_pending
                self.update_friends_list()
                print("✓ Список друзей обновлен")

        except Exception as e:
            print(f"Ошибка проверки обновлений друзей: {e}")

    def refresh_chat_if_needed(self, chat_id):
        """Обновить чат если есть новые сообщения"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM messages WHERE chat_id = ?', (chat_id,))
            count = cursor.fetchone()[0]
            conn.close()

            if chat_id not in self._last_displayed_messages:
                self._last_displayed_messages[chat_id] = count
                self.load_chat_messages(chat_id)
            elif self._last_displayed_messages[chat_id] != count:
                self._last_displayed_messages[chat_id] = count
                self.load_chat_messages(chat_id)

        except Exception as e:
            print(f"Ошибка проверки новых сообщений: {e}")

    def check_pending_requests(self):
        """Проверка входящих запросов"""
        for friend_login in list(self.pending_requests.keys()):
            if friend_login not in self.blocked_users:
                self.show_friend_request_dialog(friend_login)

    def show_friend_request_dialog(self, friend_login):
        """Показать диалог запроса в друзья"""
        if friend_login in self.blocked_users:
            return

        # Проверяем, не показывается ли уже диалог для этого пользователя
        for widget in self.findChildren(FriendRequestDialog):
            if hasattr(widget, 'friend_login') and widget.friend_login == friend_login:
                widget.raise_()
                widget.activateWindow()
                return

        dialog = FriendRequestDialog(friend_login, self)
        result = dialog.exec()

        if result == 1:  # Принято
            success, message = self.friends_manager.accept_friend_request(friend_login)
            if not success:
                QMessageBox.warning(self, "Ошибка", message)
        elif result == 2:  # Отклонено
            success, message = self.block_manager.block_user(friend_login)
            if success:
                QMessageBox.information(self, "Успех", message)
            else:
                QMessageBox.warning(self, "Ошибка", message)

    def show_blacklist_dialog(self):
        """Показать диалог черного списка"""
        blacklist_data = [(user, blocked_at) for user, blocked_at in self.blocked_users.items()]
        dialog = BlacklistDialog(blacklist_data, self.username, self)
        dialog.exec()

    def show_add_friend_dialog(self):
        """Показать диалог добавления друга"""
        try:
            dialog = AddFriendDialog(self)
            if dialog.exec():
                friend_login = dialog.get_friend_login()
                if friend_login:
                    success, message = self.friends_manager.send_friend_request(friend_login)
                    if success:
                        QMessageBox.information(self, "Успех", message)
                    else:
                        QMessageBox.warning(self, "Ошибка", message)
        except Exception as e:
            print(f"Ошибка показа диалога добавления друга: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось добавить друга: {str(e)}")

    def get_moscow_time(self):
        """Получение текущего московского времени (UTC+3)"""
        utc_time = datetime.now(timezone.utc)
        moscow_offset = timedelta(hours=3)
        moscow_time = utc_time + moscow_offset
        return moscow_time

    def get_chat_id(self, target, chat_type):
        """Получение ID чата"""
        if chat_type == "personal":
            users = sorted([self.username, target])
            return f"personal_{users[0]}_{users[1]}"
        return None

    def save_message(self, chat_id, sender, message, message_type="normal"):
        """Сохранение сообщения"""
        return self.message_manager.save_message(chat_id, sender, message, message_type)

    def update_chat_display(self, username):
        """Обновить отображение чата"""
        if self.current_chat == username and self.current_chat_type == "personal":
            chat_id = self.get_chat_id(username, "personal")
            self.load_chat_messages(chat_id)

    def update_friends_list(self):
        """Обновление списка друзей"""
        try:
            self.friends_list.clear()

            # Показываем сначала друзей
            for friend in self.friends:
                if friend in self.blocked_users or friend in self.blocked_by_users:
                    continue

                chat_id = self.get_chat_id(friend, "personal")
                last_message = self.message_manager.get_last_message(chat_id)

                if last_message:
                    sender, message, msg_type, timestamp = last_message
                    display_message = message[:30] + "..." if len(message) > 30 else message

                    if msg_type == "system":
                        item_text = f"👤 {friend}\n  ⚙️ {display_message}"
                    else:
                        prefix = "Вы: " if sender == self.username else f"{friend}: "
                        item_text = f"👤 {friend}\n  💬 {prefix}{display_message}"
                else:
                    item_text = f"👤 {friend}\n  📭 Нет сообщений"

                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, f"friend_{friend}")
                item.setFont(QFont("Segoe UI", 10))
                item.setForeground(QColor(76, 175, 80))
                self.friends_list.addItem(item)

            # Показываем входящие запросы
            for requester in self.pending_requests.keys():
                if requester not in self.blocked_users:
                    item = QListWidgetItem(f"❓ {requester}\n  📨 Запрос в друзья")
                    item.setData(Qt.UserRole, f"request_{requester}")
                    item.setFont(QFont("Segoe UI", 10))
                    item.setForeground(QColor(255, 193, 7))
                    self.friends_list.addItem(item)

            # Удаляем дублирующиеся элементы
            self.remove_duplicate_friends()

        except Exception as e:
            print(f"Ошибка обновления списка друзей: {e}")
            traceback.print_exc()

    def remove_duplicate_friends(self):
        """Удаление дублирующихся друзей из списка"""
        seen_items = set()
        for i in range(self.friends_list.count() - 1, -1, -1):
            item = self.friends_list.item(i)
            item_text = item.text().split('\n')[0]
            if item_text in seen_items:
                self.friends_list.takeItem(i)
            else:
                seen_items.add(item_text)

    def select_friend_chat(self, item):
        """Выбор чата с другом или запросом"""
        try:
            data = item.data(Qt.UserRole)

            if data.startswith("friend_"):
                # Чат с другом
                friend_login = data.replace("friend_", "")

                # Проверяем, не открыт ли уже этот чат
                chat_id = self.get_chat_id(friend_login, "personal")
                if chat_id in self._open_chats:
                    print(f"⚠ Чат с {friend_login} уже открыт")
                    return

                self.current_chat = friend_login
                self.current_chat_type = "personal"
                self.chat_header.setText(f"💬 Чат с {friend_login}")

                # Добавляем чат в множество открытых
                self._open_chats.add(chat_id)

                # Проверяем блокировки
                if friend_login in self.blocked_users:
                    # Мы заблокировали этого пользователя
                    self.chat_controls.show()
                    self.block_user_btn.setEnabled(True)
                    self.send_button.setEnabled(False)
                    self.message_input.setPlaceholderText(f"Вы добавили пользователя {friend_login} в черный список")
                    self.chat_header.setText(f"🚫 Чат с {friend_login} (заблокирован)")

                elif friend_login in self.blocked_by_users:
                    # Этот пользователь заблокировал нас
                    self.chat_controls.hide()
                    self.send_button.setEnabled(False)
                    self.message_input.setPlaceholderText(f"Пользователь {friend_login} добавил(а) вас в черный список")
                    self.chat_header.setText(f"🚫 Чат с {friend_login} (заблокирован)")

                else:
                    # Обычный чат с другом
                    self.chat_controls.show()
                    self.block_user_btn.setEnabled(True)
                    self.send_button.setEnabled(True)
                    self.message_input.setPlaceholderText(
                        "Введите сообщение... (Enter - отправить, Ctrl+Enter - новая строка)")

                # Загрузка истории чата
                self.load_chat_messages(chat_id)

            elif data.startswith("request_"):
                # Входящий запрос
                requester = data.replace("request_", "")
                self.show_friend_request_dialog(requester)

        except Exception as e:
            print(f"Ошибка выбора чата: {e}")
            traceback.print_exc()
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть чат: {str(e)}")

    def load_chat_messages(self, chat_id):
        """Загрузка и отображение сообщений чата"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT sender, message, message_type, timestamp 
                FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp
            ''', (chat_id,))
            messages = cursor.fetchall()
            print(f"📄 Загружено {len(messages)} сообщений из чата {chat_id}")
        except Exception as e:
            print(f"Ошибка загрузки сообщений: {e}")
            traceback.print_exc()
            messages = []
        finally:
            if conn:
                conn.close()

        try:
            self.messages_display.clear()
            if not messages:
                html_content = """<html><head><style>
                    body { font-family: 'Segoe UI', Arial; font-size: 13px; color: #D0D0D0; }
                    .empty { text-align: center; padding: 50px; color: #7F7F7F; font-style: italic; }
                </style></head><body>
                <div class="empty">Нет сообщений</div>
                </body></html>"""
                self.messages_display.setHtml(html_content)
                return

            html_content = """<html><head><style>
                body { font-family: 'Segoe UI', Arial; font-size: 13px; color: #D0D0D0; }
                .message { margin: 10px 0; padding: 8px 12px; border-radius: 8px; }
                .system { color: #A0A0A0; font-style: italic; text-align: center; background-color: #2D2D30; }
                .own { color: #4ECDC4; background-color: #1E3A5F; margin-left: 60px; margin-right: 20px; }
                .other { color: #FFFFFF; background-color: #2D2D30; margin-left: 20px; margin-right: 60px; }
                .time { color: #7F7F7F; font-size: 11px; display: block; margin-top: 4px; }
                .sender { font-weight: bold; margin-bottom: 4px; display: block; }
                .blocked { color: #FF6B6B; font-style: italic; text-align: center; }
            </style></head><body>"""

            for sender, message, msg_type, timestamp in messages:
                # Форматируем время
                try:
                    if ' ' in timestamp:
                        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                    else:
                        dt = datetime.strptime(timestamp, "%H:%M:%S")

                    time_str = dt.strftime("%H:%M")
                    date_str = dt.strftime("%d.%m")
                except Exception as e:
                    print(f"Ошибка парсинга времени {timestamp}: {e}")
                    time_str = timestamp[-8:-3] if len(timestamp) >= 8 else timestamp
                    date_str = ""

                if msg_type == "system":
                    html_content += f"""
                    <div class="message system">
                        {self.escape_html(message)}
                        <span class="time">[{time_str}]</span>
                    </div>
                    """
                elif "черный список" in message.lower() or "блокирован" in message.lower():
                    html_content += f"""
                    <div class="message blocked">
                        ⚠️ {self.escape_html(message)}
                        <span class="time">[{time_str}]</span>
                    </div>
                    """
                else:
                    is_own = (sender == self.username)
                    sender_class = "own" if is_own else "other"
                    sender_display = "Вы" if is_own else sender

                    html_content += f"""
                    <div class="message {sender_class}">
                        <span class="sender">{sender_display}</span>
                        {self.escape_html(message)}
                        <span class="time">[{date_str} {time_str}]</span>
                    </div>
                    """

            html_content += "</body></html>"
            self.messages_display.setHtml(html_content)

            # Прокручиваем вниз
            scrollbar = self.messages_display.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

        except Exception as e:
            print(f"Ошибка отображения сообщений: {e}")
            traceback.print_exc()

    def escape_html(self, text):
        """Экранирование HTML-символов"""
        if not text:
            return ""
        return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#039;')
                .replace('\n', '<br>'))

    def _on_message_notification(self, message):
        """Callback для уведомлений о новых сообщениях"""
        try:
            if not message or not hasattr(message, 'author'):
                return

            print(f"🔔 Callback уведомление: сообщение от {message.author}")

            if hasattr(message, 'author') and message.author == self.username:
                print(f"🔔 Игнорируем callback для собственного сообщения")
                return

            self.handle_incoming_message(message)

        except Exception as e:
            print(f"✗ Ошибка в callback уведомления: {e}")
            traceback.print_exc()

    @Slot(object)
    def handle_incoming_message(self, message):
        """Обработка входящего сообщения"""
        try:
            if not message or not hasattr(message, 'text') or not hasattr(message, 'author'):
                print(f"⚠ Получено некорректное сообщение")
                return

            text = message.text
            sender = message.author

            print(f"📨 Получено сообщение от {sender}: {text[:50]}...")

            if sender == self.username:
                print(f"📝 Игнорируем собственное сообщение (уже обработано)")
                return

            if sender in self.blocked_users:
                print(f"⚠ Сообщение от заблокированного пользователя {sender}")
                return

            if sender in self.blocked_by_users:
                print(f"⚠ Пользователь {sender} заблокировал вас")
                return

            if sender not in self.friends:
                print(f"⚠ Сообщение от не-друга {sender}, игнорируем")
                return

            chat_id = self.get_chat_id(sender, "personal")
            saved = self.save_message(chat_id, sender, text)

            if saved:
                if chat_id in self._last_displayed_messages:
                    self._last_displayed_messages[chat_id] += 1
                else:
                    self._last_displayed_messages[chat_id] = 1

                print(f"✓ Сообщение сохранено в чат {chat_id}")

                if self.current_chat == sender and self.current_chat_type == "personal":
                    print(f"✓ Обновляем отображение текущего чата")
                    self.load_chat_messages(chat_id)

                self.update_friends_list()

        except Exception as e:
            print(f"✗ Ошибка обработки входящего сообщения: {e}")
            traceback.print_exc()

    @Slot(str)
    def handle_friend_request(self, sender):
        """Обработка запроса в друзья"""
        try:
            print(f"📨 Получен запрос в друзья от {sender}")

            if sender not in self.pending_requests:
                self.pending_requests[sender] = sender

            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO friends (user1, user2, status, requested_by)
                VALUES (?, ?, 'pending', ?)
            ''', (sender, self.username, sender))
            conn.commit()
            conn.close()

            self.status_bar.showMessage(f"Новый запрос в друзья от {sender}", 5000)

            self.update_friends_list()

            QTimer.singleShot(500, lambda: self.show_friend_request_dialog(sender))

        except Exception as e:
            print(f"Ошибка обработки запроса в друзья: {e}")
            traceback.print_exc()

    @Slot(str)
    def handle_friend_request_sent(self, target):
        """Обработка уведомления об отправленном запросе"""
        try:
            print(f"📤 Запрос в друзья отправлен пользователю {target}")
            self.status_bar.showMessage(f"Запрос в друзья отправлен пользователю {target}", 3000)
        except Exception as e:
            print(f"Ошибка обработки уведомления об отправленном запросе: {e}")

    @Slot(str, str)
    def handle_friend_accepted(self, friend1, friend2):
        """Обработка принятия запроса в друзья"""
        try:
            print(f"✅ Дружба подтверждена: {friend1} и {friend2}")

            if self.username == friend1:
                new_friend = friend2
            elif self.username == friend2:
                new_friend = friend1
            else:
                return

            if new_friend not in self.friends:
                self.friends.append(new_friend)

            if new_friend in self.pending_requests:
                del self.pending_requests[new_friend]

            self.update_friends_list()

            self.status_bar.showMessage(f"Вы теперь друзья с {new_friend}!", 5000)
            QMessageBox.information(self, "Успех", f"Вы теперь друзья с {new_friend}!")

        except Exception as e:
            print(f"Ошибка обработки принятия дружбы: {e}")
            traceback.print_exc()

    @Slot(str, str)
    def handle_friend_rejected(self, rejected_by, rejected_user):
        """Обработка отклонения запроса в друзья"""
        try:
            print(f"❌ Запрос в друзья отклонен: {rejected_by} отклонил {rejected_user}")

            if self.username == rejected_user:
                self.status_bar.showMessage(f"Пользователь {rejected_by} отклонил ваш запрос в друзья", 5000)
                QMessageBox.warning(self, "Запрос отклонен",
                                    f"Пользователь {rejected_by} отклонил ваш запрос в друзья.")

        except Exception as e:
            print(f"Ошибка обработки отклонения дружбы: {e}")
            traceback.print_exc()

    @Slot(str, str)
    def handle_friend_info(self, friend_name, status):
        """Обработка информации о друге"""
        try:
            print(f"ℹ️ Информация о друге: {friend_name} - {status}")

            if status == "accepted" and friend_name not in self.friends:
                self.friends.append(friend_name)
                self.update_friends_list()

        except Exception as e:
            print(f"Ошибка обработки информации о друге: {e}")

    @Slot(str, str)
    def handle_user_blocked(self, blocker, blocked):
        """Обработка блокировки пользователя"""
        try:
            print(f"🚫 Получено уведомление о блокировке: {blocker} заблокировал {blocked}")
            if blocked == self.username:
                self.blocked_by_users[blocker] = self.get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")
                if blocker in self.friends:
                    self.friends.remove(blocker)
                self.status_bar.showMessage(f"Пользователь {blocker} заблокировал вас", 5000)
                if self.current_chat == blocker:
                    self.message_input.setPlaceholderText(f"Пользователь {blocker} добавил(а) вас в черный список")
                    self.send_button.setEnabled(False)
                self.update_friends_list()
        except Exception as e:
            print(f"Ошибка обработки блокировки: {e}")
            traceback.print_exc()

    @Slot(str, str)
    def handle_user_unblocked(self, unblocker, unblocked):
        """Обработка разблокировки пользователя"""
        try:
            print(f"🔓 Получено уведомление о разблокировки: {unblocker} разблокировал {unblocked}")
            if unblocked == self.username and unblocker in self.blocked_by_users:
                del self.blocked_by_users[unblocker]
                self.status_bar.showMessage(f"Пользователь {unblocker} разблокировал вас", 5000)
                if self.current_chat == unblocker:
                    self.message_input.setPlaceholderText(
                        "Введите сообщение... (Enter - отправить, Ctrl+Enter - новая строка)")
                    if unblocker in self.friends:
                        self.send_button.setEnabled(True)
                self.update_friends_list()
        except Exception as e:
            print(f"Ошибка обработки разблокировки: {e}")
            traceback.print_exc()

    def block_current_user(self):
        """Блокировка текущего пользователя"""
        try:
            if not self.current_chat or self.current_chat_type != "personal":
                return

            dialog = BlockUserDialog(self.current_chat, self)
            if dialog.exec():
                success, message = self.block_manager.block_user(self.current_chat)
                if success:
                    QMessageBox.information(self, "Успех", message)
                else:
                    QMessageBox.warning(self, "Ошибка", message)
        except Exception as e:
            print(f"Ошибка блокировки пользователя: {e}")
            QMessageBox.warning(self, "Ошибка", f"Не удалось заблокировать пользователя: {str(e)}")

    def send_message(self):
        """Отправка сообщения"""
        self.message_manager.send_message(self.message_input.toPlainText().strip())

    def clear_input(self):
        """Очистка поля ввода"""
        try:
            self.message_input.clear()
        except Exception as e:
            print(f"Ошибка очистки поля ввода: {e}")

    @Slot(str)
    def show_connection_error(self, error_message):
        """Показать ошибку соединения"""
        try:
            QMessageBox.warning(self, "Ошибка соединения", error_message)
        except Exception as e:
            print(f"Ошибка показа сообщения об ошибке: {e}")

    def keyPressEvent(self, event):
        """Обработка горячих клавиш"""
        try:
            if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
                if event.modifiers() & Qt.ControlModifier:
                    self.message_input.setFocus()
                    self.message_input.insertPlainText("\n")
                else:
                    if self.message_input.hasFocus() and self.send_button.isEnabled():
                        self.send_message()
                        event.accept()
                        return

            super().keyPressEvent(event)
        except Exception as e:
            print(f"Ошибка обработки клавиши: {e}")
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        try:
            print("🔒 Закрытие окна чата...")

            # Останавливаем таймеры
            if self._message_check_timer:
                self._message_check_timer.stop()

            if hasattr(self, '_friends_check_timer') and self._friends_check_timer:
                self._friends_check_timer.stop()

            # Останавливаем MessageReceiver
            if hasattr(self, 'message_receiver') and self.message_receiver:
                try:
                    print("⏹ Останавливаю MessageReceiver...")
                    self.message_receiver.stop()
                    if self.message_receiver.isRunning():
                        self.message_receiver.quit()
                        self.message_receiver.wait(1000)
                    print("✓ MessageReceiver остановлен")
                except Exception as e:
                    print(f"✗ Ошибка остановки MessageReceiver: {e}")

            # Закрываем gRPC клиент
            if hasattr(self, 'grpc_client') and self.grpc_client:
                try:
                    print("🔌 Закрываю gRPC клиент...")
                    self.grpc_client.close()
                    print("✓ gRPC клиент закрыт")
                except Exception as e:
                    print(f"✗ Ошибка закрытия gRPC клиента: {e}")

            print("✓ Окно чата закрыто")
            event.accept()
        except Exception as e:
            print(f"✗ Критическая ошибка при закрытии окна: {e}")
            traceback.print_exc()
            event.accept()