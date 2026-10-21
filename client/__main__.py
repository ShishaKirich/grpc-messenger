"""Запуск клиента:  python -m client"""
import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .ui.login_window import LoginWindow
from .ui.main_window import MainWindow
from .ui.theme import STYLESHEET


class App:
    """Переключает окна: вход → главное окно → (выход) → снова вход."""

    def __init__(self, qt_app: QApplication):
        self.qt_app = qt_app
        self.window = None
        self.show_login()

    def show_login(self, notice: str = ""):
        login = LoginWindow(notice)
        login.logged_in.connect(self.show_main)
        self._swap(login)

    def show_main(self, messenger, new_device: bool):
        main = MainWindow(messenger, new_device)
        main.logged_out.connect(self.show_login)
        self._swap(main)

    def _swap(self, window):
        old, self.window = self.window, window
        window.show()
        if old is not None:
            old.close()
            old.deleteLater()


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s: %(message)s")
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Лес из Шишек")
    qt_app.setStyle("Fusion")
    qt_app.setFont(QFont("Segoe UI", 10))
    qt_app.setStyleSheet(STYLESHEET)
    _app = App(qt_app)  # noqa: F841 — держим ссылку, пока работает цикл событий
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
