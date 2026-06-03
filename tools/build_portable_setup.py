"""
构建一键安装/启动 exe（内嵌程序 payload.zip）。

  venv\\Scripts\\python.exe tools\\build_portable_setup.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
_EMBED_PYTHON_VERSION = "3.12.10"
_EMBED_PYTHON_URL = (
    f"https://www.python.org/ftp/python/{_EMBED_PYTHON_VERSION}/"
    f"python-{_EMBED_PYTHON_VERSION}-embed-amd64.zip"
)
_EMBED_ZIP_NAME = "python-embed-amd64.zip"
_MIN_EMBED_ZIP_BYTES = 8_000_000


def _ensure_installer_assets(py: Path) -> tuple[Path, Path, Path, Path]:
    assets = ROOT / "installer_assets"
    assets.mkdir(parents=True, exist_ok=True)
    get_pip = assets / "get-pip.py"
    if not get_pip.is_file():
        print(f"[INFO] downloading get-pip.py -> {get_pip}")
        urllib.request.urlretrieve(_GET_PIP_URL, get_pip)
    embed_zip = assets / _EMBED_ZIP_NAME
    if not embed_zip.is_file() or embed_zip.stat().st_size < _MIN_EMBED_ZIP_BYTES:
        print(f"[INFO] downloading embed python -> {embed_zip}")
        urllib.request.urlretrieve(_EMBED_PYTHON_URL, embed_zip)
    bootstrap_wheels = _ensure_bootstrap_wheels(py)
    install_wheels = _ensure_install_wheels(py)
    return get_pip, embed_zip, bootstrap_wheels, install_wheels


def _ensure_install_wheels(py: Path) -> Path:
    """预下载 requirements-install.txt 全部 wheel（CI 在 Windows+Py3.12 上执行）。"""
    wheels_dir = ROOT / "installer_assets" / "install_wheels"
    req = ROOT / "requirements-install.txt"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    need = not (
        any(wheels_dir.glob("ctranslate2-*.whl"))
        and any(wheels_dir.glob("PyQt5-*.whl"))
        and any(wheels_dir.glob("argostranslate-*.whl"))
    )
    if need:
        print(f"[INFO] downloading install wheels -> {wheels_dir}")
        subprocess.check_call(
            [
                str(py),
                "-m",
                "pip",
                "download",
                "-r",
                str(req),
                "-d",
                str(wheels_dir),
                "--prefer-binary",
                "--proxy",
                "",
                "-i",
                "https://pypi.org/simple",
                "--trusted-host",
                "pypi.org",
                "--trusted-host",
                "files.pythonhosted.org",
            ],
            cwd=str(ROOT),
        )
    count = len(list(wheels_dir.glob("*.whl")))
    total_mb = sum(f.stat().st_size for f in wheels_dir.glob("*.whl")) / (1024 * 1024)
    print(f"[OK] install_wheels: {count} files, {total_mb:.1f} MB")
    return wheels_dir


def _ensure_bootstrap_wheels(py: Path) -> Path:
    wheels_dir = ROOT / "installer_assets" / "bootstrap_wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)
    need = not (
        any(wheels_dir.glob("pip-*.whl"))
        and any(wheels_dir.glob("setuptools-*.whl"))
        and any(wheels_dir.glob("wheel-*.whl"))
    )
    if need:
        print(f"[INFO] downloading bootstrap wheels -> {wheels_dir}")
        subprocess.check_call(
            [
                str(py),
                "-m",
                "pip",
                "download",
                "pip",
                "setuptools",
                "wheel",
                "-d",
                str(wheels_dir),
                "--only-binary",
                ":all:",
                "--proxy",
                "",
                "-i",
                "https://pypi.org/simple",
                "--trusted-host",
                "pypi.org",
                "--trusted-host",
                "files.pythonhosted.org",
            ],
            cwd=str(ROOT),
        )
    return wheels_dir


def main() -> int:
    py = ROOT / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
        print(f"[INFO] using interpreter: {py}")

    subprocess.check_call([str(py), str(ROOT / "tools" / "build_update_package.py")], cwd=str(ROOT))

    zips = sorted((ROOT / "dist" / "update").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        print("[ERROR] update zip not found")
        return 1
    payload_dst = ROOT / "dist" / "app_payload.zip"
    shutil.copy2(zips[-1], payload_dst)
    print(f"[OK] payload -> {payload_dst}")

    subprocess.check_call([str(py), "-m", "pip", "install", "pyinstaller"], cwd=str(ROOT))

    icon = ROOT / "assets" / "app_icon.ico"
    icon_args: list[str] = ["--icon", str(icon)] if icon.is_file() else []
    out_dir = ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)

    get_pip, embed_zip, bootstrap_wheels, install_wheels = _ensure_installer_assets(py)
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "ArgosTranslate",
        "--paths",
        str(ROOT),
        "--hidden-import",
        "portable_installer",
        "--hidden-import",
        "portable_paths",
        "--hidden-import",
        "portable_updater",
        "--hidden-import",
        "install_wizard",
        "--hidden-import",
        "app_version",
        "--hidden-import",
        "network_policy",
        "--hidden-import",
        "win_path_utils",
        "--hidden-import",
        "portable_ui_theme",
        "--add-data",
        f"{get_pip}{sep}.",
        "--add-data",
        f"{embed_zip}{sep}.",
        "--add-data",
        f"{bootstrap_wheels}{sep}bootstrap_wheels",
        "--add-data",
        f"{install_wheels}{sep}install_wheels",
        "--add-data",
        f"{payload_dst}{sep}.",
        "--add-data",
        f"{ROOT / 'assets' / 'app_icon.ico'}{sep}assets",
        "--distpath",
        str(out_dir),
        "--workpath",
        str(ROOT / "build" / "setup_work"),
        "--specpath",
        str(ROOT / "build"),
        *icon_args,
        str(ROOT / "setup_main.py"),
    ]
    print("[INFO]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))
    built = out_dir / "ArgosTranslate.exe"
    print(f"[OK] {built}")
    print("Users only need this exe: pick install folder, auto setup, then launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
