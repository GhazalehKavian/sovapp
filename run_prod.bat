@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title sovapp - محیط عملیاتی و اصلی (Port 8000)
set SOVAPP_ENV=production
set PORT=8000
python server.py
pause
