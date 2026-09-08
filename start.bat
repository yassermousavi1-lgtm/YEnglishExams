@echo off
title YEnglish Exams - Flask Server

echo ========================================
echo     YEnglish Exams - Flask Server
echo ========================================
echo.

set TELEGRAM_BOT_TOKEN=8909221623:AAE0Y0Joy7w2luQAUncMn6-0Sk9lL4AfVY0
set TEACHER_TELEGRAM_ID=231716006

echo [1] Telegram Bot Token: CONFIGURED
echo [2] Teacher ID: CONFIGURED
echo.

echo [3] Starting Flask Server...
echo.

C:\PortableApps\WPy64-313150\WPy64-313150\python\python.exe api.py

pause