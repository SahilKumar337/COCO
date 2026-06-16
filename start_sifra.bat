@echo off
title SIFRA AI - Startup Engine

echo =======================================================
echo   SIFRA AI - LOCAL JARVIS ENGINE
echo   Booting system...
echo =======================================================

:: Navigate to the directory where this script is located
cd /d "%~dp0"

:: Start the Watchdog which boots the server and monitors it
start "" /MIN python watchdog.py

echo SIFRA has been started in the background.
echo You can access the interface at: http://localhost:8000
timeout /t 3 >nul
exit
