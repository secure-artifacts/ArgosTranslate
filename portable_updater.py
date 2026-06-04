"""
便携版 ArgosTranslate 就地更新：用新版本文件覆盖安装目录，保留 data/（语言包、术语、缓存、语音模型等）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

from app_version import (
    APP_NAME,
    APP_VERSION,
    compare_versions,
    read_version_json,
    version_info_dict,
    write_version_json,
)

# 相对安装根目录的路径（文件或目录）；目录会递归复制
UPDATE_REL_PATHS: tuple[str, ...] = (
    "app_version.py",
    "app_icon_utils.py",
    "version.json",
    "assets/app_icon.ico",
    "assets/app_icon.png",
    "portable_updater.py",
    "portable_launcher.py",
    "updater_main.py",
    "run_gui.bat",
    "本地翻译器.bat",
    "本地翻译器.exe",
    "requirements-offline-speech.txt",
    "bulk_text.py",
    "glossary_editor.py",
    "glossary_inflection.py",
    "slavic_grammar_rules.py",
    "slavic_idioms.py",
    "slavic_advanced_morph.py",
    "slavic_pro_register.py",
    "data/idioms",
    "glossary_manager.py",
    "goroh_parser.py",
    "inflection_display.py",
    "lookup_icon_data.py",
    "offline_speech.py",
    "portable_ui_theme.py",
    "terminology_bridge.py",
    "translation_history.py",
    "translation_quality.py",
    "translation_tab_page.py",
    "translation_source_edit.py",
    "portable_paths.py",
    "win_path_utils.py",
    "network_policy.py",
    "portable_installer.py",
    "install_wizard.py",
    "install_location_dialog.py",
    "requirements-install.txt",
    "setup_main.py",
    "setup_boot.py",
    "github_update.py",
    "update_dialog.py",
    "slavic_translation_hints.py",
    "slavic_translation_enhance.py",
    "slavic_to_zh_enhance.py",
    "zh_to_slavic_enhance.py",
    "argos_inference_tuning.py",
    "argos_cpu_tuning.py",
    "argos_enhance.py",
    "argos_quality_guard.py",
    "argos_translation_quality.py",
    "bkrs_parser.py",
    "translation_memory.py",
    "review_queue_dialog.py",
    "corpus_pipeline/lang_filter.py",
    "lang_pair_filter.py",
    "tm_paste_import_dialog.py",
    "tm_viewer_dialog.py",
    "tm_glossary_help.py",
    "tm_manage_actions.py",
    "segmented_manuscript_panel.py",
    "corpus_pipeline",
    "bidirectional_terminology.py",
    "slavic_lemma_rank.py",
    "slavic_collocation_rank.py",
    "native_fluency_config.py",
    "native_fluency_pipeline.py",
    "news_style_rerank.py",
    "post_edit_ru.py",
    "post_edit_uk.py",
    "data/collocations",
    "data/style",
    "data/terminology",
    "data/glossary/international",
    "terminology_registry.py",
    "requirements-corpus-rerank.txt",
    "language_catalog.py",
    "ensure_language_packages.py",
    "native_dll_bootstrap.py",
    "wiktionary_parser.py",
    "word_info_dialog.py",
    "word_lookup_store.py",
    "word_notebook_dialog.py",
    "uk_lookup_bridge.py",
    "ui_session.py",
    "startup_warmup.py",
    "vcredist_helper.py",
    "tools/apply_portable_gui_patch.py",
    "tools/build_ru_uk_from_opus_zip.py",
    "tools/build_uk_ru_from_opus_zip.py",
    "patches/argostranslategui_gui.py",
    "命令",
)

PRESERVE_TOP_DIRS = frozenset({"data"})

# 允许随更新包覆盖的 data/ 子路径（程序内置术语/搭配，不含用户术语库与缓存）
_DATA_UPDATE_PREFIXES = (
    "data/idioms",
    "data/collocations",
    "data/style",
    "data/terminology",
    "data/glossary/international",
)

_PRIVATE_REL_PATHS = frozenset(
    {
        "data/config/translation_history.json",
        "data/config/word_lookup_notebook.json",
        "data/config/ui_session.json",
        "data/config/ui_prefs.json",
        "data/config/glossary_gui_prefs.json",
        "data/config/speech_audio.json",
    }
)


def _data_path_updatable(rel: Path) -> bool:
    s = rel.as_posix()
    return any(s == p or s.startswith(f"{p}/") for p in _DATA_UPDATE_PREFIXES)


def _skip_payload_rel(rel: Path) -> bool:
    if rel.as_posix() in _PRIVATE_REL_PATHS:
        return True
    if rel.suffix == ".pyc":
        return True
    return "__pycache__" in rel.parts


def install_pointer_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("USERPROFILE") or "."
    return Path(base) / "ArgosTranslatePortable" / "install_path.txt"


def save_install_pointer(target: Path) -> None:
    p = install_pointer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(target.resolve()), encoding="utf-8")


def load_install_pointer() -> Path | None:
    p = install_pointer_path()
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
        root = Path(text)
        if _is_install_root(root):
            return root.resolve()
    except OSError:
        pass
    return None


def _is_install_root(path: Path) -> bool:
    return (path / "terminology_bridge.py").is_file() and (
        path / "venv" / "Scripts" / "pythonw.exe"
    ).is_file()


def find_install_root(
    *,
    explicit: Path | None = None,
    search_near: Path | None = None,
) -> Path | None:
    if explicit is not None:
        p = explicit.resolve()
        if _is_install_root(p):
            return p
        return None
    saved = load_install_pointer()
    if saved is not None:
        return saved
    if search_near is None:
        search_near = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    cur = search_near.resolve()
    for _ in range(6):
        if _is_install_root(cur):
            return cur
        for sub in ("ArgosTranslate",):
            cand = cur / sub
            if _is_install_root(cand):
                return cand.resolve()
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def collect_payload_files(payload_root: Path) -> list[Path]:
    """列出 payload 目录中将要复制的文件（相对 payload_root）。"""
    root = payload_root.resolve()
    out: list[Path] = []
    seen: set[Path] = set()
    for rel in UPDATE_REL_PATHS:
        src = root / rel
        if not src.exists():
            continue
        if src.is_file():
            rel_path = src.relative_to(root)
            if _skip_payload_rel(rel_path):
                continue
            if rel_path not in seen:
                seen.add(rel_path)
                out.append(rel_path)
            continue
        if src.is_dir():
            for f in src.rglob("*"):
                if f.is_file():
                    rel_path = f.relative_to(root)
                    if rel_path.parts and rel_path.parts[0] in PRESERVE_TOP_DIRS:
                        if not _data_path_updatable(rel_path):
                            continue
                    if _skip_payload_rel(rel_path):
                        continue
                    if rel_path not in seen:
                        seen.add(rel_path)
                        out.append(rel_path)
    return sorted(out)


def read_payload_version(payload_root: Path) -> str:
    data = read_version_json(payload_root)
    return str(data.get("version") or APP_VERSION)


def read_installed_version(target_root: Path) -> str:
    data = read_version_json(target_root)
    return str(data.get("version") or "0.0.0")


def apply_update(
    payload_root: Path,
    target_root: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> tuple[int, list[str]]:
    """
    将 payload 复制到 target。返回 (复制文件数, 错误列表)。
    """
    payload_root = payload_root.resolve()
    target_root = target_root.resolve()
    errors: list[str] = []
    count = 0

    def log(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    files = collect_payload_files(payload_root)
    if not files:
        errors.append(f"更新包为空或路径不对：{payload_root}")
        return 0, errors

    for rel in files:
        src = payload_root / rel
        dst = target_root / rel
        if not src.is_file():
            continue
        if rel.parts and rel.parts[0] in PRESERVE_TOP_DIRS:
            if not _data_path_updatable(rel):
                continue
        log(f"更新 {rel}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
        except OSError as e:
            errors.append(f"{rel}: {e}")

    pv = payload_root / "version.json"
    try:
        if pv.is_file():
            shutil.copy2(pv, target_root / "version.json")
        else:
            write_version_json(target_root)
    except OSError as e:
        errors.append(f"version.json: {e}")

    save_install_pointer(target_root)
    try:
        from app_icon_utils import ensure_windows_launch_entries

        ensure_windows_launch_entries(target_root)
    except ImportError:
        pass
    try:
        from portable_installer import (
            apply_gui_patch_to_venv,
            ensure_runtime_python_deps,
        )

        apply_gui_patch_to_venv(target_root)
        ensure_runtime_python_deps(target_root)
    except ImportError:
        pass
    return count, errors


def launch_gui(target_root: Path) -> bool:
    bat = target_root / "run_gui.bat"
    if bat.is_file():
        os.startfile(str(bat))
        return True
    pyw = target_root / "venv" / "Scripts" / "pythonw.exe"
    script = target_root / "portable_launcher.py"
    if pyw.is_file() and script.is_file():
        import subprocess

        from win_path_utils import subprocess_hide_window_kwargs

        env = os.environ.copy()
        env.setdefault("XDG_DATA_HOME", str(target_root / "data" / "local"))
        env.setdefault("XDG_CONFIG_HOME", str(target_root / "data" / "config"))
        env.setdefault("XDG_CACHE_HOME", str(target_root / "data" / "cache"))
        env["ARGOS_TRANSLATE_HOME"] = str(target_root.resolve())
        try:
            from native_dll_bootstrap import runtime_env_for_root

            env.update(runtime_env_for_root(target_root))
        except ImportError:
            pass
        subprocess.Popen(
            [str(pyw), str(script)],
            cwd=str(target_root),
            env=env,
            close_fds=True,
            **subprocess_hide_window_kwargs(detached=True),
        )
        return True
    return False


def restart_application(target_root: Path) -> bool:
    """更新完成后启动新实例；当前进程应由调用方退出。"""
    target_root = target_root.resolve()
    try:
        from portable_installer import launch_app

        if (target_root / "venv" / "Scripts" / "pythonw.exe").is_file():
            launch_app(target_root)
            return True
    except ImportError:
        pass
    return launch_gui(target_root)


def update_summary(
    payload_root: Path,
    target_root: Path,
) -> dict[str, Any]:
    return {
        "payload_version": read_payload_version(payload_root),
        "installed_version": read_installed_version(target_root),
        "payload_root": str(payload_root),
        "target_root": str(target_root),
        "app_name": APP_NAME,
    }
