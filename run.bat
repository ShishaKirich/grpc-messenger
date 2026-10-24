@echo off
chcp 65001 >nul
rem «Лес из Шишек»: готовит окружение и запускает сайт, сервер мессенджера и клиент.
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo Python не найден. Установите Python 3.10+ с python.org и отметьте "Add python.exe to PATH".
  pause & exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo Нужен Python 3.10 или новее.
  pause & exit /b 1
)

if not exist .venv (
  echo [1/4] Создаю виртуальное окружение .venv ...
  %PY% -m venv .venv || (pause & exit /b 1)
)
echo [2/4] Устанавливаю зависимости ...
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt -r requirements-client.txt || (pause & exit /b 1)

if not exist .env (
  copy .env.example .env >nul
  .venv\Scripts\python -c "import secrets,re,pathlib; p=pathlib.Path('.env'); p.write_text(re.sub(r'^SECRET_KEY=.*$', 'SECRET_KEY='+secrets.token_urlsafe(48), p.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')"
  echo Создан .env со случайным SECRET_KEY. Почта в режиме console: коды будут в окне сервера и сайта.
)
echo [3/4] Сертификаты TLS для локального запуска ...
.venv\Scripts\python scripts\make_dev_cert.py

echo [4/4] Запускаю сайт (http://localhost:8000), сервер мессенджера и клиент ...
start "Сайт — Лес из Шишек" cmd /k .venv\Scripts\python -m uvicorn web.main:app --port 8000
start "Сервер мессенджера" cmd /k .venv\Scripts\python -m messenger_server.run_server
timeout /t 3 >nul
start "" http://localhost:8000
start "" .venv\Scripts\pythonw -m client
echo Готово. Второй клиент (чтобы переписываться с самим собой): run_client.bat
