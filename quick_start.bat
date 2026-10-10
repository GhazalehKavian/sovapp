@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"
title sovapp - سامانه تجمیع کارهای اجرایی
echo =====================================================================
echo   در حال راه اندازی سامانه تجمیع صندوق کارهای اجرایی (sovapp)...
echo =====================================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo [خطا] پایتون (Python 3) روی این سیستم نصب نیست.
        echo لطفا پایتون را نصب کرده و گزینه "Add Python to PATH" را تیک بزنید.
        pause
        exit /b 1
    ) else (
        set PY_CMD=py
    )
) else (
    set PY_CMD=python
)

echo [OK] پایتون شناسایی شد.
echo [OK] دیتابیس در صورت نیاز با داده های نمونه نمایشی فعال می شود.
echo [OK] در حال باز کردن مرورگر و اجرای سرور روی پورت 8000...
echo =====================================================================

set SOVAPP_ENV=production
set SOVAPP_PORT=8000
%PY_CMD% server.py
pause
