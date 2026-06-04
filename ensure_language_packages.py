"""
安装默认翻译语言包（俄/乌/英/中及 ru↔uk 直译包）。
供安装向导、启动修复与 GUI「自动下载语言包」调用。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

ProgressCb = Callable[[float, str], None]

# 先装英桥接包，再装 ru↔uk 直译（构建脚本依赖 stanza/resources.json）
INDEX_PAIRS: tuple[tuple[str, str], ...] = (
    ("ru", "en"),
    ("en", "ru"),
    ("uk", "en"),
    ("en", "uk"),
    ("en", "zh"),
    ("zh", "en"),
    ("ru", "zh"),
    ("zh", "ru"),
)

CUSTOM_BUILD_SCRIPTS: tuple[tuple[str, str, str], ...] = (
    ("tools/build_ru_uk_from_opus_zip.py", "ru", "uk"),
    ("tools/build_uk_ru_from_opus_zip.py", "uk", "ru"),
)


def _noop_progress(_frac: float, _msg: str) -> None:
    pass


def packages_root(install_root: Path) -> Path:
    return install_root / "data" / "local" / "argos-translate" / "packages"


def apply_data_env(install_root: Path) -> None:
    install_root = install_root.resolve()
    os.environ["XDG_DATA_HOME"] = str(install_root / "data" / "local")
    os.environ["XDG_CONFIG_HOME"] = str(install_root / "data" / "config")
    os.environ["XDG_CACHE_HOME"] = str(install_root / "data" / "cache")
    os.environ["ARGOS_TRANSLATE_HOME"] = str(install_root)
    os.environ.setdefault("PYTHONUTF8", "1")


def pair_is_installed(install_root: Path, from_code: str, to_code: str) -> bool:
    root = packages_root(install_root)
    if not root.is_dir():
        return False
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("from_code") != from_code or meta.get("to_code") != to_code:
            continue
        if (child / "model").is_dir() or (child / "sentencepiece.model").is_file():
            return True
    return False


def has_usable_language_packages(install_root: Path) -> bool:
    try:
        from language_catalog import load_languages_lightweight

        return bool(load_languages_lightweight(install_root.resolve()))
    except Exception:
        root = packages_root(install_root)
        if not root.is_dir():
            return False
        for child in root.iterdir():
            if (child / "metadata.json").is_file():
                return True
        return False


def missing_index_pairs(install_root: Path) -> list[tuple[str, str]]:
    return [
        pair
        for pair in INDEX_PAIRS
        if not pair_is_installed(install_root, pair[0], pair[1])
    ]


def missing_custom_pairs(install_root: Path) -> list[tuple[str, str]]:
    return [
        (fc, tc)
        for _script, fc, tc in CUSTOM_BUILD_SCRIPTS
        if not pair_is_installed(install_root, fc, tc)
    ]


def _install_index_pair(py: Path, install_root: Path, from_code: str, to_code: str) -> None:
    install_root = install_root.resolve()
    code = f"""
import os
from pathlib import Path

install_root = Path({install_root!r})
os.environ["XDG_DATA_HOME"] = str(install_root / "data" / "local")
os.environ["XDG_CONFIG_HOME"] = str(install_root / "data" / "config")
os.environ["XDG_CACHE_HOME"] = str(install_root / "data" / "cache")
os.environ["ARGOS_TRANSLATE_HOME"] = str(install_root)

import argostranslate.package as pkg

from_code, to_code = {from_code!r}, {to_code!r}
pkg.update_package_index()
available = [
    p
    for p in pkg.get_available_packages()
    if getattr(p, "type", "") != "sbd"
    and p.from_code == from_code
    and p.to_code == to_code
]
if not available:
    raise SystemExit(f"index missing {{from_code}}->{{to_code}}")
chosen = max(available, key=lambda p: str(getattr(p, "package_version", "")))
download_path = chosen.download()
try:
    pkg.install_from_path(download_path)
finally:
    try:
        os.remove(download_path)
    except OSError:
        pass
print("OK")
"""
    r = subprocess.run(
        [str(py), "-c", code],
        cwd=str(install_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-2000:]
        raise RuntimeError(tail.strip() or f"install {from_code}->{to_code} failed")


def _run_build_script(py: Path, install_root: Path, script_rel: str) -> None:
    script = install_root / script_rel
    if not script.is_file():
        raise RuntimeError(f"缺少构建脚本：{script_rel}")
    env = os.environ.copy()
    apply_data_env(install_root)
    env.update(
        {
            "XDG_DATA_HOME": os.environ["XDG_DATA_HOME"],
            "XDG_CONFIG_HOME": os.environ["XDG_CONFIG_HOME"],
            "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"],
            "ARGOS_TRANSLATE_HOME": os.environ["ARGOS_TRANSLATE_HOME"],
            "PYTHONUTF8": "1",
        }
    )
    r = subprocess.run(
        [str(py), str(script)],
        cwd=str(install_root),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-2000:]
        raise RuntimeError(f"构建 {script_rel} 失败 ({r.returncode})：\n{tail}")


def ensure_default_language_packages(
    install_root: Path,
    py: Path,
    *,
    progress: ProgressCb | None = None,
    skip_if_sufficient: bool = True,
) -> tuple[int, list[str]]:
    """
    安装默认语言包。返回 (成功安装数量, 警告/跳过说明)。
    """
    install_root = install_root.resolve()
    py = py.resolve()
    emit = progress or _noop_progress
    warnings: list[str] = []
    installed = 0

    if skip_if_sufficient and not missing_index_pairs(install_root) and not missing_custom_pairs(
        install_root
    ):
        emit(1.0, "语言包已就绪，跳过下载。")
        return 0, warnings

    if not py.is_file():
        raise RuntimeError(f"未找到 Python：{py}")

    index_missing = missing_index_pairs(install_root)
    total_steps = len(index_missing) + len(CUSTOM_BUILD_SCRIPTS)
    if total_steps == 0:
        emit(1.0, "语言包已就绪。")
        return 0, warnings

    step = 0
    emit(0.02, f"正在安装语言包（约 {total_steps} 个组件，首次需联网 10～40 分钟）…")

    for from_code, to_code in index_missing:
        step += 1
        frac = min(0.95, step / max(1, total_steps))
        label = f"{from_code} → {to_code}"
        emit(frac * 0.85, f"正在下载并安装 {label}（{step}/{total_steps}）…")
        try:
            _install_index_pair(py, install_root, from_code, to_code)
            installed += 1
            emit(frac * 0.85, f"已安装 {label}。")
        except Exception as e:
            warnings.append(f"{label}：{e}")

    for script_rel, from_code, to_code in CUSTOM_BUILD_SCRIPTS:
        if pair_is_installed(install_root, from_code, to_code):
            continue
        step += 1
        frac = min(0.98, step / max(1, total_steps))
        label = f"{from_code} → {to_code}（OPUS 直译）"
        emit(frac * 0.85 + 0.05, f"正在构建并安装 {label}（{step}/{total_steps}）…")
        try:
            _run_build_script(py, install_root, script_rel)
            if pair_is_installed(install_root, from_code, to_code):
                installed += 1
                emit(frac * 0.85 + 0.05, f"已安装 {label}。")
            else:
                warnings.append(f"{label}：构建完成但未检测到已安装包。")
        except Exception as e:
            warnings.append(f"{label}：{e}")

    if not has_usable_language_packages(install_root):
        detail = "\n".join(f"  · {w}" for w in warnings) if warnings else ""
        raise RuntimeError(
            "未能安装任何可用语言包。\n"
            "请确认网络畅通（需访问 pypi.org 与 object.pouta.csc.fi），"
            "然后在软件内点「管理语言包 → 下载语言包」重试。"
            + (f"\n\n详情：\n{detail}" if detail else "")
        )

    emit(1.0, f"语言包安装完成（本次新增 {installed} 个）。")
    if warnings:
        emit(1.0, "部分可选语言包未安装，可在「管理语言包」中手动下载。")
    return installed, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安装 ArgosTranslate 默认语言包")
    parser.add_argument(
        "install_root",
        nargs="?",
        type=Path,
        help="安装根目录（含 venv/）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="即使已有部分语言包也尝试补全缺失项",
    )
    args = parser.parse_args(argv)

    root = args.install_root
    if root is None:
        root = Path(os.environ.get("ARGOS_TRANSLATE_HOME", "")).expanduser()
    if not root or not root.is_dir():
        print("[ERROR] 请指定有效的 install_root 或设置 ARGOS_TRANSLATE_HOME。", file=sys.stderr)
        return 2

    root = root.resolve()
    py = root / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        print(f"[ERROR] 未找到 {py}", file=sys.stderr)
        return 2

    def _progress(frac: float, msg: str) -> None:
        print(f"[{int(frac * 100):3d}%] {msg}", flush=True)

    try:
        count, warns = ensure_default_language_packages(
            root,
            py,
            progress=_progress,
            skip_if_sufficient=not args.force,
        )
        for w in warns:
            print(f"[WARN] {w}", flush=True)
        print(f"[OK] language packages ready (+{count})")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
