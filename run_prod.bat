@echo off
cd /d "%~dp0"
title sovapp - Production Mode (Port 8000)
set SOVAPP_ENV=production
set PORT=8000
python server.py
pause
