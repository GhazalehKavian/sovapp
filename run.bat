@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title sovapp - سامانه تجمیع کارهای اجرایی
python server.py
pause
