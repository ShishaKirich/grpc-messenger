"""
Упрощенный запуск клиента без сложных импортов
"""
import sys
import os

# Добавляем пути
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, 'client'))

print("=" * 50)
print("Упрощенный запуск клиента")
print("=" * 50)

try:
    # Проверяем PySide6
    from PySide6.QtWidgets import QApplication

    print("✓ PySide6 доступен")

    # Импортируем ChatClient напрямую
    try:
        # Пробуем импортировать из client.py напрямую
        import importlib.util

        client_file = os.path.join(project_root, 'client', 'client.py')

        if not os.path.exists(client_file):
            print(f"✗ Файл не найден: {client_file}")
            raise FileNotFoundError(f"Файл {client_file} не найден")

        spec = importlib.util.spec_from_file_location("chatclient", client_file)
        client_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(client_module)
        ChatClient = client_module.ChatClient
        print("✓ ChatClient загружен напрямую")

    except Exception as e:
        print(f"✗ Ошибка загрузки ChatClient: {e}")
        raise

    # Импортируем main
    from main import main

    # Определяем порт
    port = 8000
    port_file = os.path.join(project_root, 'server_port.txt')
    if os.path.exists(port_file):
        with open(port_file, 'r') as f:
            try:
                port = int(f.read().strip())
                print(f"✓ Порт из файла: {port}")
            except:
                print("⚠ Использую порт по умолчанию: 8000")

    # Запускаем
    print(f"Запуск с портом: {port}")
    main(port)

except Exception as e:
    print(f"\n✗ Ошибка: {e}")
    import traceback

    traceback.print_exc()

    input("\nНажмите Enter для выхода...")
    sys.exit(1)