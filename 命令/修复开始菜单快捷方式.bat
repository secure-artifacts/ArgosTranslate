@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
pushd "%~dp0.." 2>nul
if errorlevel 1 (
    echo [ERROR] 无法进入程序目录。
    pause
    exit /b 1
)
set "ROOT=%CD%"
popd
set "PY=%ROOT%\venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] 未找到 %PY%
    echo 请在本程序安装目录下运行此脚本。
    pause
    exit /b 1
)
"%PY%" -c "from pathlib import Path; from app_icon_utils import ensure_windows_launch_entries; r=Path(r'%ROOT%'); print('OK' if ensure_windows_launch_entries(r) else 'FAIL')"
if errorlevel 1 (
    echo.
    echo [ERROR] 修复失败。
    pause
    exit /b 1
)
echo.
echo [OK] 已写入开始菜单与桌面快捷方式，并注册系统搜索项。
echo 请稍等 1～2 分钟后在开始菜单搜索：本地翻译器（俄乌）
echo 也可直接双击：%ROOT%\本地翻译器.bat
pause
endlocal
