@echo off
cd /d "%~dp0"
title sovapp - Test Mode (Port 8080)
set SOVAPP_ENV=test
set PORT=8080
python server.py
pause
