"""
从 Helsinki-NLP/opus-mt-ru-uk 构建并安装 Argos 俄语→乌克兰语直译包。

官方 argospm-index 无 ru→uk；本脚本下载 OPUS-MT 权重，转为 CTranslate2，
打包为 .argosmodel 并安装到便携目录 data/local/argos-translate/packages。

用法（在 ArgosTranslate 根目录）：
  venv\\Scripts\\python.exe tools\\build_ru_uk_argosmodel.py
  venv\\Scripts\\python.exe tools\\build_ru_uk_argosmodel.py --skip-install
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

HF_MODEL = "Helsinki-NLP/opus-mt-ru-uk"
HF_BASE = f"https://huggingface.co/{HF_MODEL}/resolve/main"
PACKAGE_VERSION = "1.0"
ARGOS_VERSION = "1.9.0"
FROM_CODE, TO_CODE = "ru", "uk"
FROM_NAME, TO_NAME = "Russian", "Ukrainian"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"已有缓存：{dest.name} ({dest.stat().st_size // 1024} KB)")
        return
    print(f"下载：{url}")

    def reporthook(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        done = block_num * block_size
        pct = min(100, int(done * 100 / total_size))
        print(f"\r  {pct:3d}% ({done // (1024 * 1024)} / {total_size // (1024 * 1024)} MB)", end="")

    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp, reporthook=reporthook)
    print()
    tmp.replace(dest)


def _ensure_build_deps() -> None:
    missing = []
    for mod in ("transformers", "torch"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        print("Installing build deps:", ", ".join(missing), "...")
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "transformers",
                "sentencepiece",
                "sacremoses",
                "torch",
                "-q",
            ]
        )


def _find_ct2_converter() -> str:
    venv_scripts = Path(sys.executable).resolve().parent
    for base in (venv_scripts, Path(shutil.which(sys.executable) or sys.executable).parent):
        for name in ("ct2-transformers-converter.exe", "ct2-transformers-converter"):
            candidate = base / name
            if candidate.is_file():
                return str(candidate)
    for name in ("ct2-transformers-converter", "ct2-transformers-converter.exe"):
        p = shutil.which(name)
        if p:
            return p
    raise RuntimeError(
        "ct2-transformers-converter not found. Install ctranslate2 in this venv."
    )


def _download_hf_model(cache_dir: Path) -> Path:
    model_dir = cache_dir / "hf-opus-mt-ru-uk"
    model_dir.mkdir(parents=True, exist_ok=True)
    for fname in (
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "vocab.json",
        "source.spm",
        "target.spm",
        "pytorch_model.bin",
    ):
        _download(f"{HF_BASE}/{fname}", model_dir / fname)
    return model_dir


def _patch_marian_ct2_config(ct2_dir: Path) -> None:
    """Marian OPUS 模型 decoder 应从 <pad> 起译，否则输出会重复乱码。"""
    cfg_path = ct2_dir / "config.json"
    if not cfg_path.is_file():
        return
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if cfg.get("decoder_start_token") == "</s>":
        cfg["decoder_start_token"] = "<pad>"
        cfg["bos_token"] = "<pad>"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"Patched CT2 config: decoder_start_token -> <pad>")


def _convert_to_ct2(hf_dir: Path, ct2_dir: Path) -> None:
    if ct2_dir.is_dir():
        shutil.rmtree(ct2_dir)
    ct2_dir.mkdir(parents=True, exist_ok=True)
    converter = _find_ct2_converter()
    print("转换为 CTranslate2 (int8) …")
    subprocess.check_call(
        [
            converter,
            "--model",
            str(hf_dir),
            "--output_dir",
            str(ct2_dir),
            "--quantization",
            "int8",
            "--copy_files",
            "source.spm",
            "--force",
        ],
        cwd=str(_ROOT),
    )
    _patch_marian_ct2_config(ct2_dir)


def _prepare_stanza(stanza_dir: Path) -> None:
    """Argos 包内仅需 stanza/resources.json；与已安装的 ru 包共用即可。"""
    stanza_dir.mkdir(parents=True, exist_ok=True)
    for candidate in (
        _ROOT
        / "data"
        / "local"
        / "argos-translate"
        / "packages"
        / "translate-ru_en-1_9"
        / "stanza"
        / "resources.json",
        _ROOT
        / "data"
        / "local"
        / "argos-translate"
        / "packages"
        / "translate-en_ru-1_9"
        / "stanza"
        / "resources.json",
    ):
        if candidate.is_file():
            shutil.copy2(candidate, stanza_dir / "resources.json")
            print(f"Stanza resources: {candidate.parent.parent.name}")
            return
    import stanza

    print("Downloading Stanza ru tokenize (no local ru package found) ...")
    stanza.download(
        "ru",
        model_dir=str(stanza_dir),
        processors={"tokenize": "ru"},
        verbose=False,
    )


def _write_package(
    *,
    run_dir: Path,
    ct2_dir: Path,
    spm_src: Path,
    stanza_dir: Path,
) -> Path:
    zip_base = f"translate-{FROM_CODE}_{TO_CODE}-{PACKAGE_VERSION.replace('.', '_')}"
    pkg_root = run_dir / zip_base
    if pkg_root.is_dir():
        shutil.rmtree(pkg_root)
    pkg_root.mkdir(parents=True)

    model_bin = ct2_dir / "model.bin"
    if not model_bin.is_file():
        raise FileNotFoundError(f"CT2 model missing: {model_bin}")
    shutil.copy2(spm_src, pkg_root / "sentencepiece.model")
    shutil.copytree(ct2_dir, pkg_root / "model")
    shutil.copytree(stanza_dir, pkg_root / "stanza")

    readme = pkg_root / "README.md"
    readme.write_text(
        f"# {FROM_NAME} → {TO_NAME} (OPUS-MT, package {PACKAGE_VERSION})\n\n"
        "Source: Helsinki-NLP/opus-mt-ru-uk (CC-BY 4.0).\n"
        "Built for Argos Translate portable.\n",
        encoding="utf-8",
    )
    meta = {
        "package_version": PACKAGE_VERSION,
        "argos_version": ARGOS_VERSION,
        "from_code": FROM_CODE,
        "from_name": FROM_NAME,
        "to_code": TO_CODE,
        "to_name": TO_NAME,
        "reference": HF_MODEL,
    }
    (pkg_root / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return pkg_root


def _zip_package_dir(pkg_root: Path, out_zip: Path) -> Path:
    zip_base = pkg_root.name
    if out_zip.is_file():
        out_zip.unlink()
    print(f"Zipping: {out_zip}")
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(pkg_root):
            for fn in files:
                fp = Path(root) / fn
                arc = fp.relative_to(pkg_root.parent)
                zf.write(fp, arc.as_posix())
    return out_zip


def _install_package_dir(pkg_root: Path) -> Path:
    """直接复制到 packages 目录，避免解压数百 MB 的 .argosmodel。"""
    os.environ.setdefault("XDG_DATA_HOME", str(_ROOT / "data" / "local"))
    import argostranslate.package as pkg
    from argostranslate import settings
    from argostranslate.translate import get_installed_languages

    dest = settings.package_data_dir / pkg_root.name
    with pkg.package_lock:
        if dest.is_dir():
            shutil.rmtree(dest)
        shutil.copytree(pkg_root, dest)
        get_installed_languages.cache_clear()
    return dest


def _install_package(argosmodel: Path, pkg_root: Path | None = None) -> None:
    os.environ.setdefault("XDG_DATA_HOME", str(_ROOT / "data" / "local"))
    import argostranslate.package as pkg

    if pkg_root is not None and pkg_root.is_dir():
        dest = _install_package_dir(pkg_root)
        print(f"Installed (copy): {dest}")
    else:
        with pkg.package_lock:
            pkg.install_from_path(argosmodel)
    installed = [
        p
        for p in pkg.get_installed_packages()
        if p.from_code == FROM_CODE and p.to_code == TO_CODE
    ]
    if not installed:
        raise RuntimeError("ru->uk package not found after install")
    print(f"OK: {installed[0].package_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建并安装 ru→uk Argos 语言包")
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="仅生成 .argosmodel，不写入 packages 目录",
    )
    parser.add_argument(
        "--skip-convert",
        action="store_true",
        help="若已有 CTranslate2 模型则跳过转换（加快重复打包）",
    )
    parser.add_argument(
        "--install-only",
        action="store_true",
        help="仅安装已构建的 translate-ru_uk-1_0 目录（跳过下载/转换）",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_ROOT / "data" / "cache" / "ru-uk-build",
        help="下载与转换缓存目录",
    )
    args = parser.parse_args()
    cache_dir: Path = args.cache_dir
    run_dir = cache_dir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    zip_base = f"translate-{FROM_CODE}_{TO_CODE}-{PACKAGE_VERSION.replace('.', '_')}"
    pkg_root = run_dir / zip_base

    if args.install_only:
        if not (pkg_root / "model" / "model.bin").is_file():
            print(f"Missing built package: {pkg_root}")
            return 1
        argosmodel = run_dir / f"{zip_base}.argosmodel"
        if not argosmodel.is_file() or argosmodel.stat().st_size > 120 * 1024 * 1024:
            if argosmodel.is_file():
                argosmodel.unlink()
            _zip_package_dir(pkg_root, argosmodel)
        if not args.skip_install:
            _install_package(argosmodel, pkg_root=pkg_root)
            print("\nDone. Restart run_gui.bat, select Russian -> Ukrainian.")
        return 0

    _ensure_build_deps()
    hf_dir = _download_hf_model(cache_dir)
    ct2_dir = run_dir / "ct2-model"
    if args.skip_convert and (ct2_dir / "model.bin").is_file():
        print(f"跳过转换，使用已有：{ct2_dir}")
    else:
        _convert_to_ct2(hf_dir, ct2_dir)

    spm = hf_dir / "source.spm"
    if not spm.is_file():
        alt = ct2_dir / "source.spm"
        if alt.is_file():
            spm = alt
        else:
            raise FileNotFoundError("缺少 source.spm")

    stanza_dir = run_dir / "stanza"
    _prepare_stanza(stanza_dir)
    zip_base = f"translate-{FROM_CODE}_{TO_CODE}-{PACKAGE_VERSION.replace('.', '_')}"
    pkg_root = run_dir / zip_base
    if (pkg_root / "model" / "model.bin").is_file():
        print(f"Reusing package dir: {pkg_root}")
    else:
        _write_package(
            run_dir=run_dir,
            ct2_dir=ct2_dir,
            spm_src=spm,
            stanza_dir=stanza_dir,
        )
    argosmodel = run_dir / f"{zip_base}.argosmodel"
    if argosmodel.is_file() and argosmodel.stat().st_size > 120 * 1024 * 1024:
        print(f"Removing oversized zip ({argosmodel.stat().st_size // (1024 * 1024)} MB)")
        argosmodel.unlink()
    if not argosmodel.is_file():
        argosmodel = _zip_package_dir(pkg_root, argosmodel)
    print(f"\nPackage dir: {pkg_root}")
    print(f"Argosmodel:  {argosmodel} ({argosmodel.stat().st_size // (1024 * 1024)} MB)")

    if args.skip_install:
        print("(skip-install: use GUI or rerun without --skip-install)")
        return 0

    _install_package(argosmodel, pkg_root=pkg_root)
    print("\nDone. Restart run_gui.bat, select Russian -> Ukrainian.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
