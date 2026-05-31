@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
REM Portable local translator (RU/UK) - use pythonw for GUI
pushd "%~dp0" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot open the folder that contains this script.
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
if not defined ROOT (
    echo [ERROR] Failed to resolve install root.
    pause
    exit /b 1
)
if not exist "%ROOT%\venv\Scripts\pythonw.exe" (
    echo [ERROR] Missing:
    echo   "%ROOT%\venv\Scripts\pythonw.exe"
    pause
    exit /b 1
)
set "XDG_DATA_HOME=%ROOT%\data\local"
set "XDG_CONFIG_HOME=%ROOT%\data\config"
set "XDG_CACHE_HOME=%ROOT%\data\cache"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "ARGOS_FAST_STARTUP=1"
set "ARGOS_USE_OLLAMA=1"
set "OLLAMA_MODEL=qwen2.5:7b"
set "ARGOS_DEBUG=0"
cd /d "%ROOT%"

echo.
echo [Local Translator RU/UK] Starting... Window in ~2s; language packs load in background.
echo.

if exist "%ROOT%\portable_launcher.py" (
    start "" "%ROOT%\venv\Scripts\pythonw.exe" "%ROOT%\portable_launcher.py"
    endlocal
    exit /b 0
)

start "" "%ROOT%\venv\Scripts\pythonw.exe" -c "from argostranslategui import gui; gui.main()"
endlocal
exit /b 0
