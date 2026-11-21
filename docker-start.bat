@echo off
chcp 65001 >nul
cd /d "%~dp0"
docker info >nul 2>&1
if errorlevel 1 (
    echo Запустите Docker Desktop с Linux containers и повторите запуск.
    pause
    exit /b 1
)
if not exist .env copy .env.example .env >nul
docker compose up -d --build --wait
if errorlevel 1 (
    echo Запуск не завершён. Сообщения контейнера:
    docker compose logs --tail 50 app
    pause
    exit /b 1
)
docker compose exec app python manage.py create-admin --if-missing
if errorlevel 1 (
    pause
    exit /b 1
)
echo Откройте http://localhost:8000/ ^(если меняли HTTP_PORT, используйте его^).
echo Вход куратора: /admin.html
echo Для остановки используйте docker-stop.bat. База сохранится.
pause
