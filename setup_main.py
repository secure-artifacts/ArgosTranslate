"""
安装程序 / 统一启动入口（PyInstaller 打包为 ArgosTranslate-Setup.exe）。
已安装 → 直接启动；未安装 → 弹出安装向导。
"""
from __future__ import annotations

import sys

from win_path_utils import configure_windows_utf8

configure_windows_utf8()

from portable_paths import find_portable_root, is_install_root, save_install_pointer
from portable_installer import launch_app, verify_installer_bundle


def main() -> int:
    if "--check-bundle" in sys.argv:
        from portable_installer import (
            _bundled_bootstrap_wheels_dir,
            _bundled_embed_python_zip,
            _bundled_install_wheels_dir,
            bundled_payload_zip,
        )

        missing: list[str] = []
        if bundled_payload_zip() is None:
            missing.append("app_payload.zip")
        if _bundled_embed_python_zip() is None:
            missing.append("python-embed-amd64.zip")
        if _bundled_bootstrap_wheels_dir() is None:
            missing.append("bootstrap_wheels")
        if _bundled_install_wheels_dir() is None:
            missing.append("install_wheels")
        return 0 if not missing else 1

    verify_installer_bundle()

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
