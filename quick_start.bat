@echo off
chcp 65001 >nul
title sovapp - سامانه تجمیع کارهای اجرایی
echo =====================================================================
echo   در حال راه‌اندازی سامانه تجمیع صندوق کارهای اجرایی (sovapp)...
echo =====================================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    where py >nul 2>nul
    if %errorlevel% neq 0 (
        echo [خطا] پایتون (Python 3) روی این سیستم نصب نیست یا در PATH قرار ندارد.
        echo لطفاً پایتون را نصب کرده و گزینه "Add Python to PATH" را تیک بزنید.
        pause
        exit /b 1
    ) else (
        set PY_CMD=py
    )
) else (
    set PY_CMD=python
)

echo [✓] پایتون شناسایی شد.
echo [✓] دیتابیس در صورت نیاز با داده‌های نمونه نمایشی مقداردهی می‌شود.
echo [✓] در حال باز کردن مرورگر و اجرای سرور روی پورت 8000...
echo =====================================================================

set SOVAPP_ENV=production
set SOVAPP_PORT=8000
%PY_CMD% server.py
pause
