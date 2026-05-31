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
    echo [ERROR] Missing venv.
    pause
    exit /b 1
)
echo.
echo 将下载大模型（俄语约 1.8GB + 乌克兰语约 343MB），请保持网络畅通。
echo 耗时可能 10–30 分钟，请勿关闭本窗口。
echo.
"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\download_vosk_models.py" ru uk --large
echo.
pause
