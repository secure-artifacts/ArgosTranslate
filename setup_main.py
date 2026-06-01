"""
安装程序 / 统一启动入口（PyInstaller 打包为 ArgosTranslate-Setup.exe）。
已安装 → 直接启动；未安装 → 弹出安装向导。
"""
from __future__ import annotations

import sys

from portable_paths import find_portable_root, is_install_root, save_install_pointer
from portable_installer import launch_app


def main() -> int:
    root = find_portable_root()
    if not is_install_root(root):
        from install_wizard import run_install_wizard

        root = run_install_wizard()
        if root is None:
            return 1
    save_install_pointer(root)
    return launch_app(root)


if __name__ == "__main__":
    raise SystemExit(main())
