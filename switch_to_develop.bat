@echo off
cd /d "%~dp0"
title sovapp - Switch to Develop Branch
where git >nul 2>&1 && set GIT_CMD=git || set GIT_CMD="C:\Program Files\Git\cmd\git.exe"
echo [sovapp] In hale taghir be shakhe develop (Mohite Test)...
%GIT_CMD% checkout develop
echo.
echo =======================================================
echo Shoma alaan rooye shakhe develop (Mohite Test) hastid.
echo =======================================================
pause
