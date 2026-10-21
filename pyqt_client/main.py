"""main.py - Исправленная версия"""
import sys
import os
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

# Динамический импорт ChatClient
def import_chat_client():
    """Импорт ChatClient с учетом разных путей"""
    # Пути для поиска
    possible_paths = [
        os.path.join(os.path.dirname(__file__), 'client.py'),
        os.path.join(os.path.dirname(__file__), '..', 'client', 'client.py'),
        os.path.join(os.path.dirname(__file__), 'client', 'client.py'),
        'client.py',
        'client/client.py'
    ]

    for client_path in possible_paths:
        if os.path.exists(client_path):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("chat_client_module", client_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module.ChatClient
            except Exception as e:
                print(f"Не удалось импортировать из {client_path}: {e}")
                continue

    # Если не нашли, пробуем обычный импорт
    try:
        from client import ChatClient
        return ChatClient
    except ImportError:
        # Пробуем добавить путь
        client_dir = os.path.join(os.path.dirname(__file__))
        if client_dir not in sys.path:
            sys.path.append(client_dir)
        try:
            from client import ChatClient
            return ChatClient
        except ImportError as e:
            raise ImportError(f"Не удалось импортировать ChatClient: {e}")

# Импортируем наши окна
try:
    from auth_window import AuthWindow
    from chat_window import ChatWindow
    print("✓ Модули окон загружены")
except ImportError as e:
    print(f"✗ Ошибка загрузки модулей окон: {e}")
    # Пробуем альтернативные пути
    try:
        from pyqt_client.auth_window import AuthWindow
        from pyqt_client.chat_window import ChatWindow
        print("✓ Модули окон загружены из pyqt_client")
    except ImportError:
        raise

class ChatApp:
    def __init__(self, port=8000, host='127.0.0.1'):
        self.port = port
        self.host = host
        self.grpc_client = None
        self.auth_window = None
        self.chat_window = None
        self.app = None

    def start(self):
        """Запуск приложения"""
        # Создаем приложение
        self.app = QApplication(sys.argv)
        self.app.setStyle('Fusion')

        # Устанавливаем шрифт
        font = QFont("Segoe UI", 10)
        self.app.setFont(font)

        # Импортируем ChatClient
        try:
            ChatClient = import_chat_client()
            print(f"✓ ChatClient успешно импортирован")
        except ImportError as e:
            print(f"✗ Ошибка импорта ChatClient: {e}")
            QMessageBox.critical(None, "Ошибка", f"Не удалось загрузить ChatClient:\n{e}")
            return 1

        # Создаем клиент
        try:
            self.grpc_client = ChatClient(port=self.port, host=self.host)
            print(f"✓ Подключено к {self.host}:{self.port}")
        except Exception as e:
            QMessageBox.critical(None, "Ошибка",
                               f"Не удалось подключиться:\n{e}")
            return 1

        # Создаем окно авторизации
        self.auth_window = AuthWindow(self.grpc_client)

        # Подключаем сигналы
        self.auth_window.login_successful.connect(self.show_chat_window)

        # Показываем окно
        self.auth_window.show()

        print("✓ Приложение запущено")
        return self.app.exec()

    def show_chat_window(self, username):
        """Показать окно чата"""
        try:
            print(f"✓ Открываем чат для пользователя: {username}")
            self.chat_window = ChatWindow(self.grpc_client, username)
            self.auth_window.close()
            self.chat_window.show()
            print("✓ Окно чата открыто успешно")
        except Exception as e:
            print(f"✗ Ошибка открытия окна чата: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self.auth_window, "Ошибка",
                               f"Не удалось открыть чат: {e}")

def main():
    """Точка входа"""
    # Определяем порт из файла если есть
    port = 8000
    port_file = 'server_port.txt'

    if os.path.exists(port_file):
        with open(port_file, 'r') as f:
            try:
                port = int(f.read().strip())
                print(f"✓ Использую порт из файла: {port}")
            except:
                print(f"⚠ Использую порт по умолчанию: {port}")
    else:
        print(f"✓ Использую порт по умолчанию: {port}")

    print("=" * 50)
    print("Запуск мессенджера 'Лес из Шишек'")
    print("=" * 50)

    # Создаем и запускаем приложение
    chat_app = ChatApp(port=port)
    return chat_app.start()

if __name__ == '__main__':
    # Можно указать порт при запуске
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
            # Запускаем с указанным портом
            chat_app = ChatApp(port=port)
            sys.exit(chat_app.start())
        except ValueError:
            print("Использование: python main.py [порт]")
            sys.exit(main())
    else:
        sys.exit(main())