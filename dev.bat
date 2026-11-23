@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local;%USERPROFILE%\.local\bin;%PATH%"

echo [dev] 启动本地前后端调试环境...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" %*
if errorlevel 1 (
  echo.
  echo [dev] 启动失败，退出码 %ERRORLEVEL%
  pause
)
