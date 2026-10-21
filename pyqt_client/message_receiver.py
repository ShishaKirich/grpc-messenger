# message_receiver.py - Поток для получения сообщений
import traceback
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker
from database_manager import DatabaseManager


class MessageReceiver(QThread):
    """Поток для получения сообщений от сервера"""

    message_received = Signal(object)
    friend_request_received = Signal(str)
    friend_request_sent = Signal(str)
    friend_accepted = Signal(str, str)
    friend_rejected = Signal(str, str)
    user_blocked = Signal(str, str)
    user_unblocked = Signal(str, str)
    friend_info = Signal(str, str)
    connection_error = Signal(str)

    def __init__(self, grpc_client, username):
        super().__init__()
        self.grpc_client = grpc_client
        self.username = username
        self.running = True
        self.db = DatabaseManager()
        self._mutex = QMutex()

    def run(self):
        """Запуск потока"""
        print(f"✓ Запуск MessageReceiver для {self.username}")
        try:
            def on_message(message):
                with QMutexLocker(self._mutex):
                    if self.running and message:
                        self.process_message(message)

            if self.grpc_client:
                self.grpc_client.start_listen_message(on_message)
                print(f"✓ Прослушивание запущено для {self.username}")
            else:
                print(f"✗ GRPC клиент не инициализирован")

        except Exception as e:
            print(f"✗ Ошибка в MessageReceiver.run: {e}")
            traceback.print_exc()
            if self.running:
                self.connection_error.emit(f"Ошибка соединения: {str(e)}")

    def process_message(self, message):
        """Обработка входящего сообщения"""
        try:
            if not hasattr(message, 'text') or not message.text:
                return

            text = message.text

            if text.startswith("FRIEND_REQUEST:"):
                self.handle_friend_request(text)
            elif text.startswith("FRIEND_REQUEST_SENT:"):
                self.handle_friend_request_sent(text)
            elif text.startswith("FRIEND_ACCEPTED:"):
                self.handle_friend_accepted(text)
            elif text.startswith("FRIEND_REJECTED:"):
                self.handle_friend_rejected(text)
            elif text.startswith("FRIEND_INFO:"):
                self.handle_friend_info(text)
            elif text.startswith("BLOCKED:"):
                self.handle_blocked(text)
            elif text.startswith("UNBLOCKED:"):
                self.handle_unblocked(text)
            else:
                self.message_received.emit(message)

        except Exception as e:
            print(f"✗ Ошибка обработки сообщения: {e}")
            traceback.print_exc()

    def handle_friend_request(self, text):
        """Обработка запроса в друзья"""
        try:
            _, sender = text.split(":", 1)
            if sender and sender != self.username:
                print(f"📨 Получен запрос в друзья от {sender}")
                self.friend_request_received.emit(sender)
        except:
            pass

    def handle_friend_request_sent(self, text):
        """Обработка уведомления об отправленном запросе"""
        try:
            _, target = text.split(":", 1)
            if target:
                print(f"📤 Запрос в друзья отправлен пользователю {target}")
                self.friend_request_sent.emit(target)
        except:
            pass

    def handle_friend_accepted(self, text):
        """Обработка принятия дружбы"""
        try:
            _, friend1, friend2 = text.split(":", 2)
            if self.username in [friend1, friend2]:
                print(f"✅ Дружба подтверждена: {friend1} и {friend2}")
                self.friend_accepted.emit(friend1, friend2)
        except:
            pass

    def handle_friend_rejected(self, text):
        """Обработка отклонения дружбы"""
        try:
            _, target = text.split(":", 1)
            if target:
                print(f"❌ Запрос в друзья отклонен пользователем {target}")
                self.friend_rejected.emit(target, self.username)
        except:
            pass

    def handle_friend_info(self, text):
        """Обработка информации о друге"""
        try:
            _, friend_name, status = text.split(":", 2)
            if friend_name and friend_name != self.username:
                print(f"ℹ️ Информация о друге: {friend_name} - {status}")
                self.friend_info.emit(friend_name, status)
        except:
            pass

    def handle_blocked(self, text):
        """Обработка блокировки"""
        try:
            _, blocker, blocked = text.split(":", 2)
            if self.username == blocked:
                self.user_blocked.emit(blocker, blocked)
        except:
            pass

    def handle_unblocked(self, text):
        """Обработка разблокировки"""
        try:
            _, unblocker, unblocked = text.split(":", 2)
            if self.username == unblocked:
                self.user_unblocked.emit(unblocker, unblocked)
        except:
            pass

    def stop(self):
        """Остановка потока"""
        print("Остановка MessageReceiver...")
        with QMutexLocker(self._mutex):
            self.running = False
            if self.grpc_client:
                try:
                    self.grpc_client.close()
                except:
                    pass