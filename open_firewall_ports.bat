@echo off
chcp 65001 >nul
title sovapp - باز کردن پورت های شبکه در فایروال ویندوز
echo =====================================================================
echo   در حال ثبت مجوز پورت‌های 8000 و 8080 در فایروال ویندوز...
echo =====================================================================

powershell -Command "Start-Process cmd -ArgumentList '/c netsh advfirewall firewall add rule name=""sovapp Port 8080"" dir=in action=allow protocol=TCP localport=8080 & netsh advfirewall firewall add rule name=""sovapp Port 8000"" dir=in action=allow protocol=TCP localport=8000 & echo [OK] پورت های 8000 و 8080 در فایروال ویندوز باز شدند! & timeout /t 3' -Verb RunAs"
