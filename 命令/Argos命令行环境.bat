@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
if not exist "%ROOT%\venv\Scripts\python.exe" (
    echo [ERROR] Missing:
    echo   "%ROOT%\venv\Scripts\python.exe"
    pause
    exit /b 1
)
set "XDG_DATA_HOME=%ROOT%\data\local"
set "XDG_CONFIG_HOME=%ROOT%\data\config"
set "XDG_CACHE_HOME=%ROOT%\data\cache"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%ROOT%"
title Argos Translate CLI
echo ROOT: %ROOT%
echo XDG_DATA_HOME: %XDG_DATA_HOME%
echo Example: argos-translate --from en --to zh "Hello"
echo.
cmd /k "set PATH=%ROOT%\venv\Scripts;%PATH% && echo PATH includes venv\Scripts. Ready."
endlocal
