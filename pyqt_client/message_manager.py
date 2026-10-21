# message_manager.py - Менеджер сообщений
import sqlite3
import traceback
from datetime import datetime
from PySide6.QtWidgets import QMessageBox


class MessageManager:
    """Менеджер для работы с сообщениями"""

    def __init__(self, chat_window):
        self.chat_window = chat_window
        self.db = chat_window.db

    def save_message(self, chat_id, sender, message, message_type="normal"):
        """Сохранение сообщения в базу"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Получаем московское время
            moscow_time = self.chat_window.get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

            # Проверяем на дублирование
            cursor.execute('''
                SELECT COUNT(*) FROM messages 
                WHERE chat_id = ? AND sender = ? AND message = ? 
                AND timestamp > datetime(?, '-5 seconds')
            ''', (chat_id, sender, message, moscow_time))

            count = cursor.fetchone()[0]

            if count == 0:
                cursor.execute('''
                    INSERT OR IGNORE INTO messages (chat_id, sender, message, message_type, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                ''', (chat_id, sender, message, message_type, moscow_time))
                conn.commit()
                print(f"💾 Сообщение сохранено: {sender} -> {chat_id} в {moscow_time}")
                return True
            else:
                print(f"⚠ Пропускаем дублирующее сообщение: {sender}: {message[:50]}...")
                return False

        except Exception as e:
            print(f"✗ Ошибка сохранения сообщения: {e}")
            traceback.print_exc()
            return False
        finally:
            if conn:
                self.db.close_connection(conn)

    def get_last_message(self, chat_id):
        """Получение последнего сообщения из чата"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT sender, message, message_type, timestamp 
                FROM messages 
                WHERE chat_id = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
            ''', (chat_id,))
            message = cursor.fetchone()
            return message
        except Exception as e:
            print(f"Ошибка получения последнего сообщения: {e}")
            traceback.print_exc()
            return None
        finally:
            if conn:
                self.db.close_connection(conn)

    def send_message(self, text):
        """Отправка сообщения"""
        try:
            if not self.chat_window.current_chat:
                QMessageBox.warning(self.chat_window, "Ошибка", "Выберите чат для отправки сообщения")
                return

            text = text.strip()
            if not text:
                QMessageBox.warning(self.chat_window, "Ошибка", "Введите текст сообщения")
                return

            print(f"📤 Отправка сообщения для {self.chat_window.current_chat}: {text[:50]}...")

            # Проверяем блокировки
            if self.chat_window.current_chat in self.chat_window.blocked_users:
                QMessageBox.warning(self.chat_window, "Ошибка",
                                    f"Пользователь {self.chat_window.current_chat} заблокирован")
                return

            if self.chat_window.current_chat in self.chat_window.blocked_by_users:
                QMessageBox.warning(self.chat_window, "Ошибка",
                                    f"Пользователь {self.chat_window.current_chat} заблокировал вас")
                return

            # Проверяем, друзья ли мы
            if self.chat_window.current_chat not in self.chat_window.friends:
                QMessageBox.warning(self.chat_window, "Ошибка",
                                    "Можно отправлять сообщения только друзьям")
                return

            # Форматируем сообщение
            formatted_text = f"to:{self.chat_window.current_chat} {text}"

            # Сохраняем сообщение в БД
            chat_id = self.chat_window.get_chat_id(self.chat_window.current_chat, "personal")
            saved = self.save_message(chat_id, self.chat_window.username, text)

            if not saved:
                print(f"⚠ Сообщение не сохранено (возможно дублирование)")
                return

            # Обновляем счетчик сообщений
            if chat_id in self.chat_window._last_displayed_messages:
                self.chat_window._last_displayed_messages[chat_id] += 1
            else:
                self.chat_window._last_displayed_messages[chat_id] = 1

            # Обновляем отображение
            self.chat_window.load_chat_messages(chat_id)
            self.chat_window.update_friends_list()

            # Отправляем через gRPC
            if self.chat_window.grpc_client:
                print(f"📤 Отправка через gRPC: {self.chat_window.username}: {formatted_text}")
                success = self.chat_window.grpc_client.send_message(self.chat_window.username, formatted_text)
                if not success:
                    print("⚠ Ошибка отправки через gRPC, но сообщение сохранено локально")
            else:
                print(f"⚠ GRPC клиент не доступен")

            # Очищаем поле ввода
            self.chat_window.message_input.clear()
            self.chat_window.message_input.setFocus()

            print(f"✓ Сообщение отправлено и отображено")

        except Exception as e:
            print(f"✗ Ошибка отправки сообщения: {e}")
            traceback.print_exc()
            QMessageBox.warning(self.chat_window, "Ошибка", f"Не удалось отправить сообщение: {str(e)}")