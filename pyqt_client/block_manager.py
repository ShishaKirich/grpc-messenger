# block_manager.py - Менеджер блокировок
import sqlite3
from PySide6.QtWidgets import QMessageBox


class BlockManager:
    """Менеджер для работы с блокировками"""

    def __init__(self, chat_window):
        self.chat_window = chat_window
        self.username = chat_window.username
        self.db = chat_window.db

    def block_user(self, username):
        """Блокировка пользователя"""
        if username == self.username:
            return False, "Нельзя заблокировать себя"

        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Добавляем в черный список
            cursor.execute('''
                INSERT OR REPLACE INTO blacklist (user_login, blocked_user)
                VALUES (?, ?)
            ''', (self.username, username))

            # Удаляем из друзей если были друзьями
            cursor.execute('''
                DELETE FROM friends 
                WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)
            ''', (self.username, username, username, self.username))

            # Создаем или очищаем чат
            chat_id = self.chat_window.get_chat_id(username, "personal")
            cursor.execute('DELETE FROM messages WHERE chat_id = ?', (chat_id,))

            # Добавляем системное сообщение
            self.chat_window.save_message(chat_id, "Система",
                                          f"Вы добавили пользователя {username} в черный список", "system")

            # Обновляем локальные данные
            self.chat_window.blocked_users[username] = self.chat_window.get_moscow_time().strftime("%Y-%m-%d %H:%M:%S")

            # Удаляем из друзей если был
            if username in self.chat_window.friends:
                self.chat_window.friends.remove(username)

            # Удаляем из pending_requests если был
            if username in self.chat_window.pending_requests:
                del self.chat_window.pending_requests[username]

            conn.commit()

            # Обновляем интерфейс
            self.chat_window.update_friends_list()
            if self.chat_window.current_chat == username:
                self.chat_window.update_chat_display(username)
                self.chat_window.message_input.setPlaceholderText(
                    f"Вы добавили пользователя {username} в черный список")
                self.chat_window.send_button.setEnabled(False)

            return True, f"Пользователь {username} заблокирован"

        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            return False, f"Ошибка базы данных: {str(e)}"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
        finally:
            if conn:
                self.db.close_connection(conn)

    def unblock_user(self, username):
        """Разблокировка пользователя"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Удаляем из черного списка
            cursor.execute('''
                DELETE FROM blacklist 
                WHERE user_login = ? AND blocked_user = ?
            ''', (self.username, username))

            # Добавляем системное сообщение
            chat_id = self.chat_window.get_chat_id(username, "personal")
            self.chat_window.save_message(chat_id, "Система",
                                          f"Пользователь {username} разблокирован", "system")

            # Обновляем локальные данные
            if username in self.chat_window.blocked_users:
                del self.chat_window.blocked_users[username]

            conn.commit()

            # Обновляем интерфейс
            self.chat_window.update_friends_list()

            return True, f"Пользователь {username} разблокирован"

        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            return False, f"Ошибка базы данных: {str(e)}"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
        finally:
            if conn:
                self.db.close_connection(conn)