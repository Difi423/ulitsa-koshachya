@echo off
chcp 65001 >nul
cd /d "%~dp0"
docker compose down
echo База сохранена в Docker volume. Повторный запуск: docker-start.bat.
pause
