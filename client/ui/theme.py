"""Оформление: тёмная «лесная» тема. Все цвета в одном месте."""
import hashlib

BG = "#0e1512"
SURFACE = "#141f1b"
SURFACE_2 = "#1b2924"
SURFACE_3 = "#223530"
BORDER = "#26392f"
TEXT = "#e7f0ea"
MUTED = "#8ba398"
ACCENT = "#3ccf91"         # основной зелёный
ACCENT_HOVER = "#55dea3"
ACCENT_TEXT = "#062016"
AMBER = "#f2b84b"         # секретные чаты — янтарный, «шишечный»
AMBER_BG = "#2e2716"
DANGER = "#ef6b6b"
BUBBLE_OUT = "#1f5a44"
BUBBLE_IN = "#1d2b26"
BUBBLE_AMBER_OUT = "#4a3a17"

AVATAR_COLORS = ["#3ccf91", "#5aa9e6", "#f2b84b", "#e57373", "#b39ddb", "#4dd0e1", "#ffb74d", "#81c784"]


def avatar_color(name: str) -> str:
    digest = hashlib.sha256(name.lower().encode()).digest()
    return AVATAR_COLORS[digest[0] % len(AVATAR_COLORS)]


STYLESHEET = f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: {TEXT};
}}
QMainWindow, QWidget#root, QDialog {{ background: {BG}; }}
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}

/* поля ввода */
QLineEdit, QPlainTextEdit {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 12px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#code {{ font-size: 22pt; font-weight: 600; letter-spacing: 6px; padding: 12px; }}

/* кнопки */
QPushButton {{
    background: {SURFACE_3};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background: #2a413a; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE_2}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: none; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #2c5f4a; color: #9fc7b5; }}
QPushButton#secret {{ background: {AMBER_BG}; color: {AMBER}; border: 1px solid #5a4720; }}
QPushButton#secret:hover {{ background: #3a3119; }}
QPushButton#danger {{ background: transparent; color: {DANGER}; border: 1px solid #5a2b2b; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 4px; font-weight: 500; }}
QPushButton#link:hover {{ color: {ACCENT_HOVER}; text-decoration: underline; }}
QPushButton#link:disabled {{ color: {MUTED}; background: transparent; }}
QPushButton#icon {{ background: transparent; border: none; border-radius: 18px; padding: 6px; font-size: 14pt; min-width: 36px; }}
QPushButton#icon:hover {{ background: {SURFACE_3}; }}
QPushButton#send {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: none; border-radius: 21px;
                    min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px; font-size: 14pt; padding: 0; }}
QPushButton#send:hover {{ background: {ACCENT_HOVER}; }}

/* боковая панель и список чатов */
QFrame#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QFrame#chatHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QFrame#composer {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 12px; margin: 1px 8px; }}
QListWidget::item:hover {{ background: {SURFACE_2}; }}
QListWidget::item:selected {{ background: {SURFACE_3}; }}

QLabel#title {{ font-size: 20pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 13pt; font-weight: 700; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#small {{ color: {MUTED}; font-size: 8.5pt; }}
QLabel#section {{ color: {MUTED}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding: 10px 18px 4px; }}
QLabel#error {{ color: {DANGER}; }}
QLabel#badge {{ background: {ACCENT}; color: {ACCENT_TEXT}; border-radius: 9px; padding: 1px 7px;
                font-size: 8pt; font-weight: 700; }}
QLabel#banner {{ background: {AMBER_BG}; color: {AMBER}; border: 1px solid #5a4720; border-radius: 10px;
                 padding: 8px 12px; }}
QLabel#toast {{ background: {SURFACE_3}; border: 1px solid {BORDER}; border-radius: 12px; padding: 10px 16px; }}
QLabel#safety {{ font-family: "Consolas", "JetBrains Mono", monospace; font-size: 15pt; letter-spacing: 2px; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 18px; }}
QFrame#brand {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #103a2a, stop:1 #0e1512); }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SURFACE_3}; }}
QComboBox {{ background: {AMBER_BG}; color: {AMBER}; border: 1px solid #5a4720; border-radius: 10px; padding: 6px 10px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER}; selection-background-color: {SURFACE_3}; }}
QCheckBox {{ spacing: 8px; }}
"""
