@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0" 2>nul
if errorlevel 1 (
    echo [ERROR] Cannot open install folder.
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
set "XDG_DATA_HOME=%ROOT%\data\local"
set "XDG_CONFIG_HOME=%ROOT%\data\config"
set "XDG_CACHE_HOME=%ROOT%\data\cache"
set "PYTHONUTF8=1"

echo.
echo [Argos] 正在构建并安装 俄语 -^> 乌克兰语 直译包（OPUS-MT）...
echo 首次运行需下载约 300MB，请保持网络畅通。
echo.

"%ROOT%\venv\Scripts\python.exe" "%ROOT%\tools\build_ru_uk_from_opus_zip.py"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
    echo.
    echo [ERROR] 安装失败，错误码 %EC%
    pause
    exit /b %EC%
)
echo.
echo [OK] ru-^>uk 直译包已安装。请重启 run_gui.bat 后选择 俄语 -^> 乌克兰语。
pause
endlocal
exit /b 0
