@echo off
chcp 65001 >nul
rem Запуск SecureGate на Windows: создаёт окружение, ставит зависимости и запускает сайт.
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
  echo Нужен Python 3.10 или новее. Сейчас:
  %PY% --version
  pause & exit /b 1
)

if not exist .venv (
  echo [1/3] Создаю виртуальное окружение .venv ...
  %PY% -m venv .venv || (pause & exit /b 1)
)
echo [2/3] Устанавливаю зависимости ...
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt || (pause & exit /b 1)

if not exist .env (
  copy .env.example .env >nul
  .venv\Scripts\python -c "import secrets,re,pathlib; p=pathlib.Path('.env'); p.write_text(re.sub(r'^SECRET_KEY=.*$', 'SECRET_KEY='+secrets.token_urlsafe(48), p.read_text(encoding='utf-8'), flags=re.M), encoding='utf-8')"
  echo Создан файл .env со случайным SECRET_KEY. Почта в режиме console: коды будут в этом окне.
)

echo [3/3] Сайт запущен: http://localhost:8000   (остановить: Ctrl+C)
start "" /min cmd /c "timeout /t 4 >nul & start http://localhost:8000"
.venv\Scripts\python -m uvicorn app.main:app --port 8000
pause
