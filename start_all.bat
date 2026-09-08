@echo off
title YEnglish Exams - Launcher

echo ========================================
echo     YEnglish Exams - Launcher
echo ========================================
echo.

echo [1] Starting Flask Server...
echo.
start "Flask Server" cmd /c start.bat

timeout /t 3 /nobreak > nul

echo [2] Starting ngrok...
echo.
start "ngrok" cmd /c ngrok.bat

echo.
echo ========================================
echo All services started successfully!
echo ========================================
echo.
echo Flask: http://127.0.0.1:5000
echo ngrok: Check the ngrok window for URL
echo.
echo Close the windows to stop services.
echo ========================================

pause
