# ui_builder.py

# УБРАТЬ из PySide6.QtWidgets импорт QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QListWidget, QLabel,
    QListWidgetItem, QMenuBar, QStatusBar,
    QFrame, QTextBrowser  # QAction убрать отсюда!
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor, QAction  # QAction перенести сюда!


class UIBuilder:
    """Класс для построения пользовательского интерфейса"""

    @staticmethod
    def setup_dark_theme(window):
        """Настройка тёмной темы"""
        try:
            from PySide6.QtGui import QPalette, QColor
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.Window, QColor(45, 45, 48))
            dark_palette.setColor(QPalette.WindowText, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.Base, QColor(30, 30, 30))
            dark_palette.setColor(QPalette.AlternateBase, QColor(45, 45, 48))
            dark_palette.setColor(QPalette.Text, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.Button, QColor(45, 45, 48))
            dark_palette.setColor(QPalette.ButtonText, QColor(240, 240, 240))
            dark_palette.setColor(QPalette.BrightText, QColor(255, 255, 255))
            dark_palette.setColor(QPalette.Highlight, QColor(0, 122, 204))
            dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
            dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
            dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
            dark_palette.setColor(QPalette.PlaceholderText, QColor(127, 127, 127))
            window.setPalette(dark_palette)
        except Exception as e:
            print(f"Ошибка установки темы: {e}")

    @staticmethod
    def create_left_panel(chat_window):
        """Создание левой панели"""
        try:
            panel = QWidget()
            panel.setMaximumWidth(300)
            panel.setStyleSheet("background-color: #252526;")

            layout = QVBoxLayout(panel)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(10)

            # Имя пользователя
            user_label = QLabel(f"👤 {chat_window.username}")
            user_label.setStyleSheet("""
                QLabel {
                    color: #4ECDC4;
                    font-size: 16px;
                    font-weight: bold;
                    padding: 10px;
                    border-bottom: 1px solid #3E3E42;
                }
            """)
            layout.addWidget(user_label)

            # Кнопка добавления друга
            add_friend_btn = QPushButton("➕ Добавить друга")
            add_friend_btn.setStyleSheet("""
                QPushButton {
                    background-color: #0E639C;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 10px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #1177BB;
                }
            """)
            add_friend_btn.clicked.connect(chat_window.show_add_friend_dialog)
            layout.addWidget(add_friend_btn)

            # Кнопка черного списка
            blacklist_btn = QPushButton("🚫 Черный список")
            blacklist_btn.setStyleSheet("""
                QPushButton {
                    background-color: #D32F2F;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 10px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #F44336;
                }
            """)
            blacklist_btn.clicked.connect(chat_window.show_blacklist_dialog)
            layout.addWidget(blacklist_btn)

            # Список друзей
            friends_label = QLabel("Друзья")
            friends_label.setStyleSheet("""
                QLabel {
                    color: #D0D0D0;
                    font-size: 14px;
                    font-weight: bold;
                    margin-top: 10px;
                }
            """)
            layout.addWidget(friends_label)

            chat_window.friends_list = QListWidget()
            chat_window.friends_list.setStyleSheet("""
                QListWidget {
                    background-color: #2D2D30;
                    border: 1px solid #3E3E42;
                    border-radius: 4px;
                    color: #FFFFFF;
                    outline: none;
                }
                QListWidget::item {
                    padding: 10px;
                    border-bottom: 1px solid #3E3E42;
                    background-color: #2D2D30;
                }
                QListWidget::item:hover {
                    background-color: #3E3E42;
                }
                QListWidget::item:selected {
                    background-color: #0E639C;
                }
            """)
            chat_window.friends_list.itemClicked.connect(chat_window.select_friend_chat)
            layout.addWidget(chat_window.friends_list)

            layout.addStretch()

            return panel
        except Exception as e:
            print(f"Ошибка создания левой панели: {e}")
            import traceback
            traceback.print_exc()
            raise

    @staticmethod
    def create_right_panel(chat_window):
        """Создание правой панели"""
        try:
            panel = QWidget()

            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            # Заголовок чата
            chat_window.chat_header = QLabel("Выберите чат")
            chat_window.chat_header.setStyleSheet("""
                QLabel {
                    background-color: #252526;
                    color: #FFFFFF;
                    font-size: 16px;
                    font-weight: bold;
                    padding: 15px;
                    border-bottom: 1px solid #3E3E42;
                }
            """)
            chat_window.chat_header.setAlignment(Qt.AlignCenter)
            layout.addWidget(chat_window.chat_header)

            # Кнопки управления чатом
            chat_window.chat_controls = QFrame()
            chat_window.chat_controls.setStyleSheet("background-color: #252526;")
            chat_window.chat_controls.hide()

            controls_layout = QHBoxLayout(chat_window.chat_controls)
            controls_layout.setContentsMargins(10, 5, 10, 5)

            chat_window.block_user_btn = QPushButton("🚫 Заблокировать")
            chat_window.block_user_btn.setStyleSheet("""
                QPushButton {
                    background-color: #D32F2F;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #F44336;
                }
                QPushButton:disabled {
                    background-color: #3C3C3C;
                    color: #6B6B6B;
                }
            """)
            chat_window.block_user_btn.clicked.connect(chat_window.block_current_user)
            chat_window.block_user_btn.setEnabled(False)

            controls_layout.addWidget(chat_window.block_user_btn)
            controls_layout.addStretch()

            layout.addWidget(chat_window.chat_controls)

            # Область сообщений
            chat_window.messages_display = QTextBrowser()
            chat_window.messages_display.setOpenExternalLinks(True)
            chat_window.messages_display.setStyleSheet("""
                QTextBrowser {
                    background-color: #1E1E1E;
                    color: #D0D0D0;
                    border: none;
                    padding: 15px;
                    font-size: 13px;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    selection-background-color: #264F78;
                }
                QTextBrowser:focus {
                    border: none;
                    outline: none;
                }
            """)
            layout.addWidget(chat_window.messages_display, 4)

            # Область ввода сообщения
            input_frame = QFrame()
            input_frame.setStyleSheet("background-color: #252526; border-top: 1px solid #3E3E42;")

            input_layout = QVBoxLayout(input_frame)
            input_layout.setContentsMargins(15, 15, 15, 15)
            input_layout.setSpacing(10)

            # Поле ввода сообщения
            chat_window.message_input = QTextEdit()
            chat_window.message_input.setPlaceholderText(
                "Введите сообщение... (Enter - отправить, Ctrl+Enter - новая строка)")
            chat_window.message_input.setStyleSheet("""
                QTextEdit {
                    background-color: #2D2D30;
                    border: 2px solid #3E3E42;
                    border-radius: 6px;
                    padding: 12px;
                    color: #FFFFFF;
                    font-size: 14px;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    min-height: 80px;
                    max-height: 150px;
                    selection-background-color: #264F78;
                }
                QTextEdit:focus {
                    border: 2px solid #007ACC;
                }
                QTextEdit::placeholder {
                    color: #686868;
                    font-style: italic;
                }
            """)
            input_layout.addWidget(chat_window.message_input)

            # Панель кнопок
            button_layout = QHBoxLayout()
            button_layout.setSpacing(10)

            chat_window.send_button = QPushButton("Отправить (Enter)")
            chat_window.send_button.setStyleSheet("""
                QPushButton {
                    background-color: #0E639C;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 14px;
                    padding: 12px 24px;
                    min-height: 40px;
                }
                QPushButton:hover {
                    background-color: #1177BB;
                }
                QPushButton:pressed {
                    background-color: #0C547D;
                }
                QPushButton:disabled {
                    background-color: #3C3C3C;
                    color: #6B6B6B;
                }
            """)
            chat_window.send_button.clicked.connect(chat_window.send_message)
            chat_window.send_button.setEnabled(False)

            clear_button = QPushButton("Очистить")
            clear_button.setStyleSheet("""
                QPushButton {
                    background-color: #7F8C8D;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 14px;
                    padding: 12px 24px;
                    min-height: 40px;
                }
                QPushButton:hover {
                    background-color: #95A5A6;
                }
            """)
            clear_button.clicked.connect(chat_window.clear_input)

            button_layout.addStretch()
            button_layout.addWidget(clear_button)
            button_layout.addWidget(chat_window.send_button)

            input_layout.addLayout(button_layout)
            layout.addWidget(input_frame, 1)

            return panel
        except Exception as e:
            print(f"Ошибка создания правой панели: {e}")
            import traceback
            traceback.print_exc()
            raise

    @staticmethod
    def create_menu(chat_window):
        """Создание меню"""
        try:
            menubar = chat_window.menuBar()
            menubar.setStyleSheet("""
                QMenuBar {
                    background-color: #252526;
                    color: #D0D0D0;
                    border-bottom: 1px solid #3E3E42;
                }
                QMenuBar::item {
                    padding: 5px 10px;
                    background-color: transparent;
                }
                QMenuBar::item:selected {
                    background-color: #3E3E42;
                }
            """)

            # Меню Файл
            file_menu = menubar.addMenu("Файл")
            exit_action = QAction("Выход", chat_window)
            exit_action.setShortcut("Ctrl+Q")
            exit_action.triggered.connect(chat_window.close)
            file_menu.addAction(exit_action)

            # Меню Настройки
            settings_menu = menubar.addMenu("Настройки")
            blacklist_action = QAction("Черный список", chat_window)
            blacklist_action.triggered.connect(chat_window.show_blacklist_dialog)
            settings_menu.addAction(blacklist_action)
        except Exception as e:
            print(f"Ошибка создания меню: {e}")