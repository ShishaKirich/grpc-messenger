# dialogs.py - Все диалоговые окна
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QDialogButtonBox,
    QFormLayout, QFrame, QMessageBox,
    QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class AddFriendDialog(QDialog):
    """Диалог для отправки запроса в друзья"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Добавить друга")
        self.setMinimumWidth(300)

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()
        self.friend_login_input = QLineEdit()
        self.friend_login_input.setPlaceholderText("Введите логин друга")
        form_layout.addRow("Логин друга:", self.friend_login_input)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_friend_login(self):
        return self.friend_login_input.text().strip()


class FriendRequestDialog(QDialog):
    """Диалог для принятия/отклонения запроса в друзья"""

    def __init__(self, friend_login, parent=None):
        super().__init__(parent)
        self.friend_login = friend_login
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Запрос в друзья")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        message_label = QLabel(
            f"Пользователь <b>{self.friend_login}</b> хочет добавить вас в друзья."
        )
        message_label.setWordWrap(True)
        message_label.setStyleSheet("font-size: 13px; padding: 10px;")
        layout.addWidget(message_label)

        info_label = QLabel(
            "После принятия:\n"
            "• Вы станете друзьями\n"
            "• Сможете обмениваться сообщениями\n\n"
            "После отклонения:\n"
            "• Пользователь будет заблокирован\n"
            "• Он не сможет отправлять вам запросы"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #A0A0A0; font-size: 12px; padding: 10px;")
        layout.addWidget(info_label)

        button_layout = QHBoxLayout()

        accept_btn = QPushButton("✅ Принять")
        accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #388E3C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #43A047;
            }
        """)
        accept_btn.clicked.connect(lambda: self.done(1))

        reject_btn = QPushButton("❌ Отклонить")
        reject_btn.setStyleSheet("""
            QPushButton {
                background-color: #D32F2F;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #F44336;
            }
        """)
        reject_btn.clicked.connect(lambda: self.done(2))

        button_layout.addWidget(accept_btn)
        button_layout.addWidget(reject_btn)

        layout.addLayout(button_layout)


class BlockUserDialog(QDialog):
    """Диалог для блокировки пользователя"""

    def __init__(self, username, parent=None):
        super().__init__(parent)
        self.username = username
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Блокировка пользователя")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)

        warning_label = QLabel(
            f"Вы уверены, что хотите заблокировать пользователя <b>{self.username}</b>?"
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("color: #FF6B6B; font-size: 13px;")
        layout.addWidget(warning_label)

        consequences_label = QLabel(
            "После блокировки:\n"
            "• Вы не сможете получать сообщения от этого пользователя\n"
            "• Он не сможет отправлять вам сообщения\n"
            "• Вы сможете разблокировать его позже в настройках"
        )
        consequences_label.setWordWrap(True)
        consequences_label.setStyleSheet("color: #A0A0A0; font-size: 12px; padding: 10px;")
        layout.addWidget(consequences_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
        buttons.button(QDialogButtonBox.Yes).setText("Заблокировать")
        buttons.button(QDialogButtonBox.No).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class BlacklistDialog(QDialog):
    """Диалог для просмотра черного списка"""

    def __init__(self, blacklist_data, current_user, parent=None):
        super().__init__(parent)
        self.blacklist_data = blacklist_data
        self.current_user = current_user
        self.parent_window = parent
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("Черный список")
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)

        title_label = QLabel("🔒 Заблокированные пользователи")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #FFFFFF;
                padding: 10px;
                background-color: #252526;
                border-radius: 4px;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1E1E1E;
            }
            QScrollBar:vertical {
                background-color: #2D2D30;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #3E3E42;
                border-radius: 6px;
                min-height: 20px;
            }
        """)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(5, 5, 5, 5)
        scroll_layout.setSpacing(5)

        if self.blacklist_data:
            for blocked_user, blocked_at in self.blacklist_data:
                user_frame = QFrame()
                user_frame.setFrameStyle(QFrame.Box)
                user_frame.setStyleSheet("""
                    QFrame {
                        background-color: #2D2D30;
                        border-radius: 6px;
                        border: 1px solid #3E3E42;
                        padding: 10px;
                    }
                """)

                user_layout = QHBoxLayout(user_frame)

                user_info = QVBoxLayout()

                username_label = QLabel(f"👤 {blocked_user}")
                username_label.setStyleSheet("color: #FFFFFF; font-size: 14px; font-weight: bold;")

                from datetime import datetime
                try:
                    blocked_date = datetime.strptime(blocked_at, "%Y-%m-%d %H:%M:%S")
                    date_str = blocked_date.strftime("%d.%m.%Y %H:%M")
                except:
                    date_str = blocked_at

                date_label = QLabel(f"Заблокирован: {date_str}")
                date_label.setStyleSheet("color: #A0A0A0; font-size: 11px;")

                user_info.addWidget(username_label)
                user_info.addWidget(date_label)

                user_layout.addLayout(user_info)
                user_layout.addStretch()

                unblock_btn = QPushButton("Разблокировать")
                unblock_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #388E3C;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        padding: 8px 16px;
                        font-size: 12px;
                        min-width: 100px;
                    }
                    QPushButton:hover {
                        background-color: #43A047;
                    }
                """)
                unblock_btn.clicked.connect(lambda checked, u=blocked_user: self.unblock_user(u))

                user_layout.addWidget(unblock_btn)
                scroll_layout.addWidget(user_frame)
        else:
            empty_label = QLabel("Черный список пуст")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setStyleSheet("""
                QLabel {
                    color: #A0A0A0;
                    font-size: 14px;
                    padding: 40px;
                    font-style: italic;
                }
            """)
            scroll_layout.addWidget(empty_label)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)

        close_btn = QPushButton("Закрыть")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #0E639C;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 12px;
                font-size: 14px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background-color: #1177BB;
            }
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def unblock_user(self, username):
        """Разблокировать пользователя"""
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Вы уверены, что хотите разблокировать пользователя {username}?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            if self.parent_window:
                self.parent_window.unblock_user(username)
                self.accept()