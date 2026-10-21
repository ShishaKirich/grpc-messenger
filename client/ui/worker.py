"""Фоновые потоки, чтобы окно не зависало, пока идёт запрос к серверу или Argon2.

run_async(fn, ..., on_done=..., on_error=...) — выполнить fn в пуле потоков,
а результат передать обратно в поток интерфейса через сигналы Qt.
EventStream — постоянный поток событий с сервера с переподключением.
"""
import logging
import time

import grpc
from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal

from ..api import ApiError

log = logging.getLogger("client")
_running: set = set()   # держим ссылки на задачи, пока они не завершились


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args, self.signals = fn, args, _Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except ApiError as exc:
            self.signals.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001 — показываем ошибку, а не роняем приложение
            log.exception("Ошибка в фоновой задаче")
            self.signals.failed.emit(f"Непредвиденная ошибка: {exc}")
        else:
            self.signals.done.emit(result)


def run_async(fn, *args, on_done=None, on_error=None) -> None:
    """Вызывать из потока интерфейса: туда же вернутся on_done/on_error."""
    task = _Task(fn, args)
    task.setAutoDelete(False)  # объектом владеет Python, а не пул Qt
    # задачу отпускаем только после того, как ответ дошёл до потока интерфейса
    task.signals.done.connect(lambda _: _running.discard(task))
    task.signals.failed.connect(lambda _: _running.discard(task))
    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    _running.add(task)
    QThreadPool.globalInstance().start(task)


class EventStream(QThread):
    updates = Signal(object)        # список core.Update
    online = Signal(bool)
    session_lost = Signal(str)

    def __init__(self, messenger):
        super().__init__()
        self.messenger = messenger
        self._call = None
        self._stopped = False

    def run(self):
        delay = 1
        while not self._stopped:
            try:
                self._call = self.messenger.api.subscribe()
                self.online.emit(True)
                delay = 1
                for event in self._call:
                    updates = self.messenger.handle_event(event)
                    if updates:
                        self.updates.emit(updates)
            except grpc.RpcError as exc:
                if self._stopped or exc.code() == grpc.StatusCode.CANCELLED:
                    break
                if exc.code() == grpc.StatusCode.UNAUTHENTICATED:
                    self.session_lost.emit(exc.details() or "Сеанс завершён.")
                    break
            except Exception:  # noqa: BLE001
                log.exception("Ошибка в потоке событий")
            if self._stopped:
                break
            self.online.emit(False)
            time.sleep(delay)
            delay = min(delay * 2, 30)   # переподключаемся всё реже, чтобы не долбить сервер

    def stop(self):
        self._stopped = True
        if self._call is not None:
            self._call.cancel()
        self.wait(3000)
