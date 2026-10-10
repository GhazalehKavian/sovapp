@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title sovapp - محیط تستی (Port 8080)
set SOVAPP_ENV=test
set PORT=8080
python server.py
pause
