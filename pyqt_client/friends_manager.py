# friends_manager.py - Менеджер друзей и черного списка
import sqlite3
import traceback
from datetime import datetime
from PySide6.QtWidgets import QMessageBox


class FriendsManager:
    """Менеджер для работы с друзьями и черным списком"""

    def __init__(self, chat_window):
        self.chat_window = chat_window
        self.username = chat_window.username
        self.db = chat_window.db

    def load_friends(self):
        """Загрузка подтвержденных друзей"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    CASE 
                        WHEN user1 = ? THEN user2 
                        ELSE user1 
                    END as friend
                FROM friends 
                WHERE (user1 = ? OR user2 = ?) 
                    AND status = 'accepted'
            ''', (self.username, self.username, self.username))
            friends = [row[0] for row in cursor.fetchall()]
            return friends
        except Exception as e:
            print(f"Ошибка загрузки друзей: {e}")
            traceback.print_exc()
            return []
        finally:
            if conn:
                self.db.close_connection(conn)

    def load_blocked_users(self):
        """Загрузка заблокированных пользователей"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Кого мы заблокировали
            cursor.execute('''
                SELECT blocked_user, blocked_at 
                FROM blacklist 
                WHERE user_login = ?
            ''', (self.username,))

            blocked_users = {}
            for row in cursor.fetchall():
                blocked_user, blocked_at = row
                blocked_users[blocked_user] = blocked_at

            # Кто нас заблокировал
            cursor.execute('''
                SELECT user_login, blocked_at 
                FROM blacklist 
                WHERE blocked_user = ?
            ''', (self.username,))

            blocked_by_users = {}
            for row in cursor.fetchall():
                blocker, blocked_at = row
                blocked_by_users[blocker] = blocked_at

            return blocked_users, blocked_by_users

        except Exception as e:
            print(f"Ошибка загрузки черного списка: {e}")
            traceback.print_exc()
            return {}, {}
        finally:
            if conn:
                self.db.close_connection(conn)

    def load_pending_requests(self):
        """Загрузка входящих запросов в друзья"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            requests = {}
            cursor.execute('''
                SELECT user1, requested_by 
                FROM friends 
                WHERE user2 = ? AND status = 'pending'
            ''', (self.username,))

            for row in cursor.fetchall():
                user1, requested_by = row
                requests[user1] = requested_by
            return requests
        except Exception as e:
            print(f"Ошибка загрузки запросов: {e}")
            traceback.print_exc()
            return {}
        finally:
            if conn:
                self.db.close_connection(conn)

    def send_friend_request(self, friend_login):
        """Отправка запроса в друзья"""
        if friend_login == self.username:
            return False, "Нельзя добавить себя в друзья"

        # Проверяем блокировки
        if friend_login in self.chat_window.blocked_users:
            return False, "Вы заблокировали этого пользователя"

        if friend_login in self.chat_window.blocked_by_users:
            return False, "Этот пользователь заблокировал вас"

        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # Проверяем существующие отношения
            cursor.execute('''
                SELECT status FROM friends 
                WHERE (user1 = ? AND user2 = ?) OR (user1 = ? AND user2 = ?)
            ''', (self.username, friend_login, friend_login, self.username))

            existing = cursor.fetchone()

            if existing:
                status = existing[0]
                if status == 'accepted':
                    return False, "Этот пользователь уже у вас в друзьях"
                elif status == 'pending':
                    return False, "Запрос уже отправлен"

            # Создаем новый запрос
            cursor.execute('''
                INSERT INTO friends (user1, user2, status, requested_by)
                VALUES (?, ?, 'pending', ?)
            ''', (self.username, friend_login, self.username))

            # Создаем чат для запроса
            chat_id = self.chat_window.get_chat_id(friend_login, "personal")
            self.chat_window.save_message(chat_id, "Система",
                                          "Запрос в друзья отправлен. Ожидание ответа...", "system")

            # Отправляем через gRPC
            if self.chat_window.grpc_client:
                success = self.chat_window.grpc_client.send_message(self.username, f"FRIEND_REQUEST:{friend_login}")
                if success:
                    print(f"✓ Запрос в друзья отправлен через gRPC")
                else:
                    print(f"⚠ Ошибка отправки запроса через gRPC")

            conn.commit()

            # Добавляем в локальный список
            if friend_login not in self.chat_window.pending_requests:
                self.chat_window.pending_requests[friend_login] = self.username

            # Обновляем интерфейс
            self.chat_window.update_friends_list()

            return True, f"Запрос в друзья отправлен пользователю {friend_login}"

        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            return False, f"Ошибка базы данных: {str(e)}"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
        finally:
            if conn:
                self.db.close_connection(conn)

    def accept_friend_request(self, friend_login):
        """Принятие запроса в друзья"""
        conn = None
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE friends 
                SET status = 'accepted'
                WHERE user1 = ? AND user2 = ? AND status = 'pending'
            ''', (friend_login, self.username))

            if cursor.rowcount > 0:
                # Проверяем, есть ли уже зеркальная запись
                cursor.execute('''
                    SELECT id FROM friends 
                    WHERE user1 = ? AND user2 = ? AND status = 'accepted'
                ''', (self.username, friend_login))

                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO friends (user1, user2, status, requested_by)
                        VALUES (?, ?, 'accepted', ?)
                    ''', (self.username, friend_login, friend_login))

                # Очищаем системные сообщения в чате
                chat_id = self.chat_window.get_chat_id(friend_login, "personal")
                cursor.execute('''
                    DELETE FROM messages 
                    WHERE chat_id = ? AND message_type = 'system'
                ''', (chat_id,))

                # Добавляем системное сообщение
                self.chat_window.save_message(chat_id, "Система",
                                              f"Запрос в друзья от {friend_login} принят. Теперь вы друзья!", "system")

                # Добавляем в список друзей
                if friend_login not in self.chat_window.friends:
                    self.chat_window.friends.append(friend_login)

                # Удаляем из pending_requests
                if friend_login in self.chat_window.pending_requests:
                    del self.chat_window.pending_requests[friend_login]

                # Отправляем уведомление через gRPC
                try:
                    if self.chat_window.grpc_client and hasattr(self.chat_window.grpc_client, 'send_message'):
                        self.chat_window.grpc_client.send_message(self.username,
                                                                  f"FRIEND_ACCEPTED:{self.username}:{friend_login}")
                except Exception as e:
                    print(f"Ошибка отправки gRPC уведомления: {e}")

                conn.commit()

                # Обновляем интерфейс
                self.chat_window.update_friends_list()
                if self.chat_window.current_chat == friend_login:
                    self.chat_window.load_chat_messages(chat_id)

                # Показываем уведомление
                QMessageBox.information(self.chat_window, "Успех", f"Пользователь {friend_login} добавлен в друзья!")

                return True, f"Пользователь {friend_login} добавлен в друзья"
            else:
                return False, "Запрос не найден или уже обработан"

        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            return False, f"Ошибка базы данных: {str(e)}"
        except Exception as e:
            return False, f"Ошибка: {str(e)}"
        finally:
            if conn:
                self.db.close_connection(conn)