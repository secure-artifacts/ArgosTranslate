"""PyInstaller 入口：已安装则启动，否则运行安装向导。"""
from __future__ import annotations

from setup_main import main

if __name__ == "__main__":
    raise SystemExit(main())
