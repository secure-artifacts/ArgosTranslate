@echo off
chcp 65001 >nul 2>&1
pushd "%~dp0.." 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot open ArgosTranslate folder.
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
if not exist "%ROOT%\venv\Scripts\python.exe" (
    echo [ERROR] Missing venv: "%ROOT%\venv\Scripts\python.exe"
    pause
    exit /b 1
)
echo Downloading light Vosk models (ru small + uk nano). For better quality use:
echo   命令\下载语音模型-大模型.bat
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\download_vosk_models.py" ru uk
echo.
pause
