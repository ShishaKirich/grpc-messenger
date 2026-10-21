@echo off
chcp 65001 >nul
rem Ещё одно окно клиента — например, чтобы войти вторым пользователем. Сначала запустите run.bat.
cd /d "%~dp0"
start "" .venv\Scripts\pythonw -m client
