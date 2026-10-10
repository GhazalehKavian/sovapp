@echo off
cd /d "%~dp0"
title sovapp - Switch to Main Branch
where git >nul 2>&1 && set GIT_CMD=git || set GIT_CMD="C:\Program Files\Git\cmd\git.exe"
echo [sovapp] In hale taghir be shakhe main (Mohite Asli)...
%GIT_CMD% checkout main
echo.
echo =======================================================
echo Shoma alaan rooye shakhe main (Mohite Asli / Moshtari) hastid.
echo =======================================================
pause
