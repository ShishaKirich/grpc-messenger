# styles.py - Все стили в одном месте
STYLES = {
    # Окно авторизации
    'auth_window': """
        QWidget {
            background-color: #f8f9fa;
        }
    """,

    'auth_title': """
        QLabel {
            color: #2c3e50;
            font-size: 24px;
            font-weight: bold;
        }
    """,

    'auth_subtitle': """
        QLabel {
            color: #7f8c8d;
            font-size: 14px;
        }
    """,

    'auth_label': """
        QLabel {
            color: #34495e;
            font-weight: bold;
            font-size: 13px;
        }
    """,

    'auth_input': """
        QLineEdit {
            border: 2px solid #bdc3c7;
            border-radius: 6px;
            padding: 10px;
            font-size: 14px;
            background-color: white;
            min-height: 40px;
        }
        QLineEdit:focus {
            border: 2px solid #3498db;
        }
        QLineEdit::placeholder {
            color: #95a5a6;
        }
    """,

    'auth_button_primary': """
        QPushButton {
            background-color: #3498db;
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            padding: 12px;
            min-height: 45px;
        }
        QPushButton:hover {
            background-color: #2980b9;
        }
        QPushButton:pressed {
            background-color: #1c6ea4;
        }
        QPushButton:disabled {
            background-color: #bdc3c7;
        }
    """,

    'auth_button_secondary': """
        QPushButton {
            background-color: #2ecc71;
            color: white;
            border: none;
            border-radius: 6px;
            font-weight: bold;
            font-size: 14px;
            padding: 12px;
            min-height: 45px;
        }
        QPushButton:hover {
            background-color: #27ae60;
        }
        QPushButton:pressed {
            background-color: #219653;
        }
    """,

    'auth_hint': """
        QLabel {
            color: #95a5a6;
            font-size: 12px;
        }
    """,

    'auth_separator': """
        QFrame {
            color: #bdc3c7;
        }
    """,

    # Окно чата
    'chat_window': """
        QMainWindow {
            background-color: #f8f9fa;
        }
    """,

    'chat_users_panel': """
        QWidget {
            background-color: #f8f9fa;
            border-right: 1px solid #dee2e6;
        }
    """,

    'chat_users_title': """
        QLabel {
            color: #2c3e50;
            font-size: 16px;
            font-weight: bold;
            padding: 10px;
        }
    """,

    'chat_users_list': """
        QListWidget {
            border: none;
            background-color: white;
            border-radius: 5px;
            font-size: 13px;
        }
        QListWidget::item {
            padding: 10px;
            border-bottom: 1px solid #ecf0f1;
            color: #2c3e50;
        }
        QListWidget::item:hover {
            background-color: #f8f9fa;
        }
        QListWidget::item:selected {
            background-color: #e3f2fd;
            color: #1565c0;
        }
    """,

    'chat_users_info': """
        QLabel {
            color: #95a5a6;
            font-size: 11px;
        }
    """,

    'chat_message_display': """
        QTextEdit {
            border: none;
            background-color: white;
            padding: 15px;
            font-size: 13px;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
    """,

    'chat_input_frame': """
        QFrame {
            background-color: #f8f9fa;
            border-top: 1px solid #dee2e6;
        }
    """,

    'chat_message_input': """
        QTextEdit {
            border: 1px solid #ced4da;
            border-radius: 8px;
            padding: 10px;
            background-color: white;
            font-size: 14px;
            font-family: 'Segoe UI', Arial, sans-serif;
            min-height: 80px;
            max-height: 80px;
        }
        QTextEdit:focus {
            border: 2px solid #3498db;
        }
        QTextEdit::placeholder {
            color: #adb5bd;
            font-style: italic;
        }
    """,

    'chat_send_button': """
        QPushButton {
            background-color: #3498db;
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: bold;
            font-size: 14px;
            padding: 0 30px;
            min-height: 40px;
        }
        QPushButton:hover {
            background-color: #2980b9;
        }
        QPushButton:pressed {
            background-color: #1c6ea4;
        }
        QPushButton:disabled {
            background-color: #bdc3c7;
        }
    """,

    'chat_clear_button': """
        QPushButton {
            background-color: #95a5a6;
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: bold;
            font-size: 14px;
            padding: 0 20px;
            min-height: 40px;
        }
        QPushButton:hover {
            background-color: #7f8c8d;
        }
    """,

    'status_bar': """
        QStatusBar {
            background-color: #e9ecef;
            color: #495057;
            border-top: 1px solid #dee2e6;
            font-size: 12px;
        }
    """,

    'menu_bar': """
        QMenuBar {
            background-color: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            padding: 4px;
        }
        QMenuBar::item {
            padding: 6px 12px;
            background-color: transparent;
            border-radius: 4px;
        }
        QMenuBar::item:selected {
            background-color: #e9ecef;
        }
        QMenuBar::item:pressed {
            background-color: #dee2e6;
        }
    """,

    'menu': """
        QMenu {
            background-color: white;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            padding: 4px;
        }
        QMenu::item {
            padding: 6px 24px 6px 12px;
            color: #212529;
        }
        QMenu::item:selected {
            background-color: #f8f9fa;
            color: #000;
        }
        QMenu::separator {
            height: 1px;
            background-color: #dee2e6;
            margin: 4px 0;
        }
    """
}