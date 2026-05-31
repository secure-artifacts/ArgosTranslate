"""
从 Tatoeba OPUS zho→ukr Marian 权重构建 Argos 中文→乌克兰语直译包。

数据源：欧洲 CSC 节点 object.pouta.csc.fi（非 .cn 镜像）。
默认输出 .argosmodel 到 downloads/ 供杀毒扫描后再安装。

用法（ArgosTranslate 根目录）：
  venv\\Scripts\\python.exe tools\\build_zh_uk_from_opus_zip.py --skip-install
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
OPUS_URL = (
    "https://object.pouta.csc.fi/Tatoeba-MT-models/zho-ukr/opus-2020-06-16.zip"
)
PACKAGE_VERSION = "1.0"
ZIP_BASE = "translate-zh_uk-1_0"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 10_000_000:
        print(f"cached {dest.name}")
        return
    print(f"download {url}")

    def hook(n, size, total):
        if total > 0:
            print(f"\r  {min(100, n * size * 100 // total)}%", end="")

    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp, reporthook=hook)
    print()
    tmp.replace(dest)


def _find_ct2_marian_converter() -> str:
    scripts = Path(sys.executable).resolve().parent
    for base in (scripts, Path(shutil.which(sys.executable) or sys.executable).parent):
        for name in ("ct2-marian-converter.exe", "ct2-marian-converter"):
            p = base / name
            if p.is_file():
                return str(p)
    w = shutil.which("ct2-marian-converter")
    if w:
        return w
    raise RuntimeError("ct2-marian-converter not found")


def _opus_to_ct2(opus_dir: Path, ct2_dir: Path) -> Path:
    spms = glob.glob(str(opus_dir / "*source*.spm"))
    if not spms:
        spms = glob.glob(str(opus_dir / "*.spm"))
    spm = next((p for p in spms if "source" in p.lower()), spms[0] if spms else None)
    if not spm:
        raise FileNotFoundError("no .spm in opus zip")

    npzs = glob.glob(str(opus_dir / "*.npz"))
    npz = max(npzs, key=lambda p: os.path.getsize(p)) if npzs else None
    if not npz:
        raise FileNotFoundError("no .npz in opus zip")

    vocabs = [
        v
        for v in glob.glob(str(opus_dir / "*.yml"))
        if "opus" in v.lower() and ".vocab." in v.lower() and "decoder" not in v.lower()
    ]
    if not vocabs:
        vocabs = glob.glob(str(opus_dir / "*.yml"))
    vocab = vocabs[0] if vocabs else None
    if not vocab:
        raise FileNotFoundError("no vocab yml in opus zip")

    if ct2_dir.is_dir():
        shutil.rmtree(ct2_dir)
    ct2_dir.mkdir(parents=True)
    conv = _find_ct2_marian_converter()
    print("ct2-marian-converter ...")
    subprocess.check_call(
        [
            conv,
            "--model_path",
            npz,
            "--vocab_paths",
            vocab,
            "--output_dir",
            str(ct2_dir),
            "--quantization",
            "int8",
            "--force",
        ]
    )
    return Path(spm)


def _zip_package_dir(pkg_root: Path, out_zip: Path) -> Path:
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


def _install(pkg_root: Path) -> None:
    os.environ.setdefault("XDG_DATA_HOME", str(_ROOT / "data" / "local"))
    from argostranslate import settings
    from argostranslate.translate import get_installed_languages

    dest = settings.package_data_dir / pkg_root.name
    import argostranslate.package as pkg

    with pkg.package_lock:
        if dest.is_dir():
            shutil.rmtree(dest)
        shutil.copytree(pkg_root, dest)
        get_installed_languages.cache_clear()
    print(f"installed {dest}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()

    cache = _ROOT / "data" / "cache" / "zh-uk-build" / "opus-zip"
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / "opus-2020-06-16.zip"
    extract = cache / "extracted"
    _download(OPUS_URL, zip_path)
    if extract.is_dir():
        shutil.rmtree(extract)
    extract.mkdir()
    print("extract ...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract)

    run = _ROOT / "data" / "cache" / "zh-uk-build" / "run"
    ct2_dir = run / "ct2-marian-zh-uk"
    spm_src = _opus_to_ct2(extract, ct2_dir)

    pkg_root = run / ZIP_BASE
    if pkg_root.is_dir():
        shutil.rmtree(pkg_root)
    pkg_root.mkdir()
    shutil.copy2(spm_src, pkg_root / "sentencepiece.model")
    shutil.copytree(ct2_dir, pkg_root / "model")

    stanza_candidates = (
        _ROOT
        / "data/local/argos-translate/packages/translate-zh_en-1_9/stanza/resources.json",
        _ROOT
        / "data/local/argos-translate/packages/translate-en_zh-1_9/stanza/resources.json",
        _ROOT
        / "data/local/argos-translate/packages/translate-ru_en-1_9/stanza/resources.json",
    )
    (pkg_root / "stanza").mkdir()
    for cand in stanza_candidates:
        if cand.is_file():
            shutil.copy2(cand, pkg_root / "stanza" / "resources.json")
            print(f"stanza from {cand.parent.parent.name}")
            break
    else:
        raise FileNotFoundError("no stanza/resources.json in installed zh/en packages")

    meta = {
        "package_version": PACKAGE_VERSION,
        "argos_version": "1.9.0",
        "from_code": "zh",
        "from_name": "Chinese",
        "to_code": "uk",
        "to_name": "Ukrainian",
        "reference": OPUS_URL,
    }
    (pkg_root / "metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    (pkg_root / "README.md").write_text(
        "# Chinese -> Ukrainian (OPUS-MT Tatoeba, Helsinki-NLP/opus-mt-zh-uk)\n",
        encoding="utf-8",
    )

    downloads = _ROOT / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    argosmodel = downloads / f"{ZIP_BASE}.argosmodel"
    _zip_package_dir(pkg_root, argosmodel)
    print(f"Argosmodel: {argosmodel} ({argosmodel.stat().st_size // (1024 * 1024)} MB)")

    if not args.skip_install:
        _install(pkg_root)
        import argostranslate.translate as tr

        tr.get_installed_languages.cache_clear()
        zh = next(l for l in tr.get_installed_languages() if l.code == "zh")
        uk = next(l for l in tr.get_installed_languages() if l.code == "uk")
        t = zh.get_translation(uk)
        print("test:", t.translate("你好"))

    print("done", pkg_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
