@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo =====================================================================
echo   در حال ساخت پکیج فشرده اشتراک گذاری امن (بدون دیتای حساس)...
echo =====================================================================
python scripts/package_for_sharing.py
pause
