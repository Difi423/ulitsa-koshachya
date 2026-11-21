@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 start.py %*
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Не найден Python. Установите Python 3.10 или новее с python.org.
        echo Инструкция находится в README.md.
    ) else (
        python start.py %*
    )
)
pause
