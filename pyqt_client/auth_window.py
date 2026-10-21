# auth_window.py - Окно авторизации с тёмной темой (исправленная)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QPalette, QColor


class AuthWindow(QWidget):
    """Окно авторизации и регистрации"""

    login_successful = Signal(str)  # Сигнал с именем пользователя

    def __init__(self, grpc_client):
        super().__init__()
        self.grpc_client = grpc_client
        self.setup_palette()
        self.init_ui()

    def setup_palette(self):
        """Настройка тёмной палитры для всего окна"""
        dark_palette = QPalette()

        # Основные цвета
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

        # Дополнительные цвета
        dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(127, 127, 127))
        dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
        dark_palette.setColor(QPalette.PlaceholderText, QColor(127, 127, 127))

        self.setPalette(dark_palette)

    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle("Лес из Шишек - Авторизация")
        self.setMinimumSize(420, 480)  # Минимальный размер вместо фиксированного
        self.setMaximumSize(500, 550)  # Максимальный размер

        # Основной layout с правильными отступами
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 35, 40, 35)
        main_layout.setSpacing(12)

        # Название мессенджера
        title = QLabel("🌲 Лес из Шишек")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont("Segoe UI", 22, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #4ECDC4; margin-bottom: 5px;")
        main_layout.addWidget(title)

        # Подзаголовок
        subtitle = QLabel("Вход в мессенджер")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle_font = QFont("Segoe UI", 11)
        subtitle.setFont(subtitle_font)
        subtitle.setStyleSheet("color: #A0A0A0; margin-bottom: 25px;")
        main_layout.addWidget(subtitle)

        # Форма авторизации
        form_layout = QVBoxLayout()
        form_layout.setSpacing(6)

        # Поле логина с меткой
        login_container = QVBoxLayout()
        login_container.setSpacing(4)

        login_label = QLabel("Логин:")
        login_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        login_label.setStyleSheet("color: #D0D0D0;")
        login_container.addWidget(login_label)

        self.login_input = QLineEdit()
        self.login_input.setPlaceholderText("Введите ваш логин")
        self.login_input.setMinimumHeight(40)
        self.login_input.setMaximumHeight(45)
        self.login_input.setFont(QFont("Segoe UI", 10))
        self.login_input.setStyleSheet("""
            QLineEdit {
                background-color: #2D2D30;
                border: 2px solid #3E3E42;
                border-radius: 4px;
                padding: 10px 12px;
                color: #FFFFFF;
                selection-background-color: #007ACC;
            }
            QLineEdit:focus {
                border: 2px solid #007ACC;
                background-color: #252526;
            }
            QLineEdit::placeholder {
                color: #686868;
                font-style: italic;
            }
        """)
        login_container.addWidget(self.login_input)

        form_layout.addLayout(login_container)
        form_layout.addSpacing(12)

        # Поле пароля с меткой
        password_container = QVBoxLayout()
        password_container.setSpacing(4)

        password_label = QLabel("Пароль:")
        password_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        password_label.setStyleSheet("color: #D0D0D0;")
        password_container.addWidget(password_label)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Введите ваш пароль")
        self.password_input.setMinimumHeight(40)
        self.password_input.setMaximumHeight(45)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setFont(QFont("Segoe UI", 10))
        self.password_input.setStyleSheet("""
            QLineEdit {
                background-color: #2D2D30;
                border: 2px solid #3E3E42;
                border-radius: 4px;
                padding: 10px 12px;
                color: #FFFFFF;
                selection-background-color: #007ACC;
            }
            QLineEdit:focus {
                border: 2px solid #007ACC;
                background-color: #252526;
            }
            QLineEdit::placeholder {
                color: #686868;
                font-style: italic;
            }
        """)
        password_container.addWidget(self.password_input)

        form_layout.addLayout(password_container)

        main_layout.addLayout(form_layout)
        main_layout.addSpacing(25)

        # Кнопка входа
        self.login_btn = QPushButton("Войти")
        self.login_btn.setMinimumHeight(46)
        self.login_btn.setMaximumHeight(50)
        login_btn_font = QFont("Segoe UI", 11, QFont.Weight.Medium)
        self.login_btn.setFont(login_btn_font)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #0E639C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 12px;
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
        self.login_btn.clicked.connect(self.handle_login)
        main_layout.addWidget(self.login_btn)
        main_layout.addSpacing(8)

        # Кнопка регистрации
        self.register_btn = QPushButton("Создать аккаунт")
        self.register_btn.setMinimumHeight(46)
        self.register_btn.setMaximumHeight(50)
        register_btn_font = QFont("Segoe UI", 11)
        self.register_btn.setFont(register_btn_font)
        self.register_btn.setStyleSheet("""
            QPushButton {
                background-color: #388E3C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #43A047;
            }
            QPushButton:pressed {
                background-color: #2E7D32;
            }
            QPushButton:disabled {
                background-color: #3C3C3C;
                color: #6B6B6B;
            }
        """)
        self.register_btn.clicked.connect(self.handle_register)
        main_layout.addWidget(self.register_btn)

        main_layout.addSpacing(15)

        # Информационная подсказка
        info_label = QLabel("Нет аккаунта? Нажмите 'Создать аккаунт'")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setFont(QFont("Segoe UI", 9))
        info_label.setStyleSheet("color: #A0A0A0;")
        main_layout.addWidget(info_label)

        # Ссылка на помощь
        help_label = QLabel('<a href="#" style="color: #4ECDC4; text-decoration: none;">Нужна помощь?</a>')
        help_label.setAlignment(Qt.AlignCenter)
        help_label.setFont(QFont("Segoe UI", 9))
        help_label.setOpenExternalLinks(False)
        help_label.linkActivated.connect(self.show_help)
        main_layout.addWidget(help_label)

        # Добавляем растягивающийся элемент внизу
        main_layout.addStretch()

        self.setLayout(main_layout)

        # Устанавливаем фокус на поле логина
        self.login_input.setFocus()

        # Подключаем Enter для авторизации
        self.login_input.returnPressed.connect(self.handle_login)
        self.password_input.returnPressed.connect(self.handle_login)

    def handle_login(self):
        """Обработка нажатия кнопки 'Войти'"""
        login = self.login_input.text().strip()
        password = self.password_input.text().strip()

        if not login:
            self.show_error("Введите логин")
            return
        if not password:
            self.show_error("Введите пароль")
            return

        self.set_buttons_enabled(False)
        self.login_btn.setText("Подключение...")

        try:
            token = self.grpc_client.auth(login, password)
            if token:
                print(f"✓ Успешная авторизация: {login}, токен: {token}")

                # Устанавливаем имя пользователя в клиенте
                if hasattr(self.grpc_client, 'set_username'):
                    self.grpc_client.set_username(login)
                    print(f"✓ Имя пользователя установлено в клиенте: {login}")
                else:
                    print("⚠ Клиент не поддерживает set_username")

                self.login_successful.emit(login)
            else:
                self.show_error("Неверный логин или пароль")
        except Exception as e:
            self.show_error(f"Ошибка соединения: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.set_buttons_enabled(True)
            self.login_btn.setText("Войти")

    def handle_register(self):
        """Обработка нажатия кнопки 'Регистрация'"""
        login = self.login_input.text().strip()
        password = self.password_input.text().strip()

        if not login:
            self.show_error("Введите логин")
            return
        if not password:
            self.show_error("Введите пароль")
            return
        if len(password) < 3:
            self.show_error("Пароль должен быть не менее 3 символов")
            return
        if len(login) < 3:
            self.show_error("Логин должен быть не менее 3 символов")
            return

        self.set_buttons_enabled(False)
        self.register_btn.setText("Регистрация...")

        try:
            success = self.grpc_client.register(login, password)
            if success:
                QMessageBox.information(self, "Успех",
                                        "Регистрация прошла успешно!\nТеперь вы можете войти.")
                self.password_input.clear()
                self.login_input.setFocus()
            else:
                self.show_error("Логин уже занят, попробуйте другой")

        except Exception as e:
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "занят" in error_msg.lower():
                self.show_error("Логин уже занят, попробуйте другой")
            else:
                self.show_error(f"Ошибка регистрации: {error_msg}")
        finally:
            self.set_buttons_enabled(True)
            self.register_btn.setText("Создать аккаунт")

    def show_error(self, message):
        """Показать сообщение об ошибке"""
        QMessageBox.warning(self, "Ошибка", message)
        if not self.login_input.text().strip():
            self.login_input.setFocus()
        elif not self.password_input.text().strip():
            self.password_input.setFocus()

    def show_help(self):
        """Показать справку"""
        help_text = """
        <h3>Помощь по авторизации</h3>
        <p><b>Для входа:</b></p>
        <ul>
            <li>Введите логин и пароль существующего аккаунта</li>
            <li>Нажмите кнопку <b>"Войти"</b></li>
            <li>Или нажмите <b>Enter</b> в поле пароля</li>
        </ul>

        <p><b>Для регистрации:</b></p>
        <ul>
            <li>Придумайте уникальный логин и пароль</li>
            <li>Логин должен быть не менее 3 символов</li>
            <li>Пароль должен быть не менее 3 символов</li>
            <li>Если логин уже занят - придумайте другой</li>
            <li>Нажмите кнопку <b>"Создать аккаунт"</b></li>
            <li>После регистрации войдите с теми же данными</li>
        </ul>

        <p><b>Тестовые пользователи (уже созданы):</b></p>
        <ul>
            <li>Логин: <code>Bob</code>, Пароль: <code>123</code></li>
            <li>Логин: <code>Alice</code>, Пароль: <code>123</code></li>
            <li>Логин: <code>Charlie</code>, Пароль: <code>123</code></li>
        </ul>

        <p><b>В чате:</b></p>
        <ul>
            <li><b>Enter</b> - отправить сообщение</li>
            <li><b>Ctrl+Enter</b> - новая строка в поле ввода</li>
            <li><b>Shift+Enter</b> - не работает, используйте Ctrl+Enter</li>
        </ul>

        <p><i>Совет: придумайте уникальный логин для тестирования!</i></p>
        """

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Помощь")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(help_text)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()

    def set_buttons_enabled(self, enabled):
        """Включить/выключить кнопки"""
        self.login_btn.setEnabled(enabled)
        self.register_btn.setEnabled(enabled)

    def keyPressEvent(self, event):
        """Обработка нажатия клавиш"""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.password_input.hasFocus() or self.login_input.hasFocus():
                self.handle_login()
        elif event.key() == Qt.Key_F1:
            self.show_help()
        else:
            super().keyPressEvent(event)