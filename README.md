# Мессенджер на gRPC (курсовой проект)

Клиент-серверное приложение-**мессенджер** на Python: обмен сообщениями по
**gRPC**, аутентификация пользователей, графический клиент на **PySide6 (Qt)**,
управление друзьями и блокировками, хранение данных в SQLite.

## Архитектура

- **Сервер** (`server/`) — gRPC-сервисы аутентификации (`auth.py`) и обмена
  сообщениями (`messaging.py`, `sync_messaging.py`), хранение в SQLite
- **Protobuf** (`proto/`) — описания сервисов `Auth` и `Messaging` и
  сгенерированный код
- **GUI-клиент** (`pyqt_client/`) — окна авторизации и чата на PySide6, менеджеры
  друзей/сообщений/блокировок, приём сообщений в реальном времени
- **Консольный клиент** (`client/`) — альтернативный текстовый клиент

## Технологии

`Python` · `gRPC` (`grpcio`, `grpcio-tools`) · `protobuf` · `PySide6 (Qt)` · `SQLite`

## Запуск

Исходный код проекта находится в архиве **`Forest of Cones.zip`** (каталог
`Kursach_itog`). Распакуйте его и установите зависимости:

```bash
pip install grpcio==1.62.0 grpcio-tools==1.62.0 protobuf==4.25.2 PySide6==6.6.1
# сервер
python Kursach_itog/server/run_server.py
# графический клиент
python Kursach_itog/pyqt_client/run_pyqt_client.py
```

## Структура (внутри архива)

```
Kursach_itog/
├── server/        — gRPC-сервер (аутентификация, обмен сообщениями)
├── pyqt_client/   — графический клиент на PySide6
├── client/        — консольный клиент
├── proto/         — protobuf-описания сервисов
└── requirements.txt
```
