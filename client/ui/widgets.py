"""Небольшие виджеты: аватар, строка в списке чатов, «пузырь» сообщения, всплывающая подсказка."""
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import theme


class Avatar(QWidget):
    """Кружок с первой буквой имени; цвет зависит от имени. secret=True — значок замка."""

    def __init__(self, name: str, size: int = 42, secret: bool = False, parent=None):
        super().__init__(parent)
        self.name, self.secret = name, secret
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        color = QColor(theme.AMBER if self.secret else theme.avatar_color(self.name))
        p.setBrush(color.darker(260))
        p.drawEllipse(self.rect())
        p.setPen(color)
        font = QFont(self.font())
        font.setPixelSize(int(self.height() * 0.42))
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignCenter, "🔒" if self.secret else (self.name[:1].upper() or "?"))


class ChatRow(QWidget):
    """Строка в боковой панели: аватар, имя, подпись, счётчик непрочитанных или кнопки заявки."""
    accepted = Signal()
    declined = Signal()

    def __init__(self, name: str, subtitle: str, secret: bool = False, unread: int = 0, request: bool = False,
                 dimmed: bool = False):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(12)
        row.addWidget(Avatar(name, 44, secret))

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(name)
        title.setStyleSheet(f"font-weight: 600; font-size: 10.5pt; color: {theme.AMBER if secret else theme.TEXT};")
        sub = QLabel()
        sub.setObjectName("small")
        # длинную подпись обрезаем многоточием, чтобы строка не вылезала за панель
        width = 120 if request else 190 if unread else 220
        sub.setText(sub.fontMetrics().elidedText(subtitle, Qt.ElideRight, width))
        sub.setToolTip(subtitle)
        text.addWidget(title)
        text.addWidget(sub)
        row.addLayout(text, 1)
        if dimmed:
            title.setStyleSheet(f"font-weight: 600; color: {theme.MUTED};")

        if request:
            yes, no = QPushButton("Принять"), QPushButton("✕")
            yes.setObjectName("primary")
            no.setToolTip("Отклонить")
            for b in (yes, no):
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet("padding: 6px 10px;")
            yes.clicked.connect(self.accepted)
            no.clicked.connect(self.declined)
            row.addWidget(yes)
            row.addWidget(no)
        elif unread:
            badge = QLabel(str(unread) if unread < 100 else "99+")
            badge.setObjectName("badge")
            badge.setFixedHeight(20)
            badge.setAlignment(Qt.AlignCenter)
            row.addWidget(badge, 0, Qt.AlignRight)


class Bubble(QWidget):
    """Сообщение в ленте чата."""

    def __init__(self, text: str, sent_at: int, outgoing: bool, secret: bool = False, ttl: int = 0,
                 error: bool = False):
        super().__init__()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 3, 16, 3)

        frame = QFrame()
        frame.setMaximumWidth(560)
        frame.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        bg = theme.BUBBLE_AMBER_OUT if (secret and outgoing) else theme.BUBBLE_OUT if outgoing else theme.BUBBLE_IN
        border = f"border: 1px solid {theme.DANGER};" if error else ""
        corner = "border-bottom-right-radius: 4px;" if outgoing else "border-bottom-left-radius: 4px;"
        frame.setStyleSheet(f"QFrame {{ background: {bg}; border-radius: 16px; {corner} {border} }}")
        inner = QVBoxLayout(frame)
        inner.setContentsMargins(14, 9, 14, 7)
        inner.setSpacing(3)

        body = QLabel(text)
        body.setWordWrap(True)
        # QLabel с переносом строк по умолчанию слишком узкий: задаём ширину по самой длинной строке
        longest = max((body.fontMetrics().horizontalAdvance(line) for line in text.splitlines() or [""]), default=0)
        body.setMinimumWidth(min(longest + 8, 470))
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setTextFormat(Qt.PlainText)   # никакого HTML из чужих сообщений
        body.setStyleSheet(f"background: transparent; font-size: 10.5pt; color: {theme.DANGER if error else theme.TEXT};")
        inner.addWidget(body)

        meta = [time.strftime("%H:%M", time.localtime(sent_at))]
        if ttl:
            meta.insert(0, f"⏱ {ttl_label(ttl)}")
        meta.append("🔒" if secret else "🔐")
        info = QLabel("  ".join(meta))
        info.setStyleSheet(f"background: transparent; color: {theme.MUTED}; font-size: 8pt;")
        info.setAlignment(Qt.AlignRight)
        info.setToolTip("Секретный чат: Double Ratchet, только на этом устройстве" if secret
                        else "Сквозное шифрование: сервер видит только шифротекст")
        inner.addWidget(info)

        if outgoing:
            outer.addStretch(1)
            outer.addWidget(frame)
        else:
            outer.addWidget(frame)
            outer.addStretch(1)


class SystemLine(QLabel):
    """Служебная строка посередине ленты: «секретный чат начат» и т. п."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setStyleSheet(f"color: {theme.AMBER}; font-size: 9pt; padding: 8px 40px;")


class DayLine(QLabel):
    def __init__(self, ts: int):
        day = time.strftime("%d.%m.%Y", time.localtime(ts))
        today = time.strftime("%d.%m.%Y")
        super().__init__("Сегодня" if day == today else day)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"color: {theme.MUTED}; font-size: 8.5pt; padding: 10px;")


class Toast(QLabel):
    """Короткое сообщение внизу окна, исчезает само."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_text(self, text: str, ms: int = 3500):
        self.setText(text)
        width = min(520, self.parent().width() - 40, self.fontMetrics().horizontalAdvance(text) + 40)
        self.setFixedWidth(max(width, 160))
        self.adjustSize()
        parent = self.parent()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - 90)
        self.raise_()
        self.show()
        self._timer.start(ms)


def ttl_label(ttl: int) -> str:
    if ttl < 60:
        return f"{ttl} с"
    if ttl < 3600:
        return f"{ttl // 60} мин"
    if ttl < 86400:
        return f"{ttl // 3600} ч"
    return f"{ttl // 86400} д"
