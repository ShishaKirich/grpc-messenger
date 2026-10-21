# database_manager.py - Менеджер базы данных
import sqlite3
from PySide6.QtCore import QMutex, QMutexLocker


class DatabaseManager:
    """Менеджер базы данных с исправленной блокировкой"""

    _instance = None
    _mutex = QMutex()

    def __new__(cls):
        with QMutexLocker(cls._mutex):
            if cls._instance is None:
                cls._instance = super(DatabaseManager, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._db_path = 'chat_data.db'
            self.init_database()
            self._initialized = True

    def get_connection(self):
        """Получить соединение с базой данных"""
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def close_connection(self, conn):
        """Закрыть соединение с базой данных"""
        if conn:
            try:
                conn.close()
            except:
                pass

    def init_database(self):
        """Инициализация базы данных"""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Таблица черного списка
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blacklist (
                    id INTEGER PRIMARY KEY,
                    user_login TEXT NOT NULL,
                    blocked_user TEXT NOT NULL,
                    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_login, blocked_user)
                )
            ''')

            # Таблица друзей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS friends (
                    id INTEGER PRIMARY KEY,
                    user1 TEXT NOT NULL,
                    user2 TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    requested_by TEXT NOT NULL,
                    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user1, user2)
                )
            ''')

            # Таблица сообщений
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message TEXT NOT NULL,
                    message_type TEXT DEFAULT 'normal',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Уникальный индекс
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_message 
                ON messages(chat_id, sender, message, timestamp)
            ''')

            conn.commit()
            print("✓ База данных инициализирована")
        except Exception as e:
            print(f"✗ Ошибка инициализации БД: {e}")
            import traceback
            traceback.print_exc()
            if conn:
                conn.rollback()
        finally:
            if conn:
                self.close_connection(conn)