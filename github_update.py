"""
从 GitHub Releases 检查并下载 ArgosTranslate 程序更新包（zip）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app_version import APP_VERSION, compare_versions, read_version_json
from portable_paths import find_portable_root, is_install_root
from portable_updater import apply_update, read_installed_version

ProgressCb = Callable[[str], None]

DEFAULT_GITHUB_REPO = "secure-artifacts/ArgosTranslate"
_API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
_TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+)", re.I)


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    html_url: str
    body: str
    zip_url: str
    zip_name: str
    zip_size: int


def _read_settings_key(key: str) -> str:
    custom = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if custom:
        path = Path(custom) / "argos-translate" / "settings.json"
    else:
        root = find_portable_root()
        path = root / "data" / "config" / "argos-translate" / "settings.json"
    if not path.is_file():
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            return str(raw.get(key, "") or "").strip()
    except (OSError, json.JSONDecodeError):
        pass
    return ""


def github_repo() -> str:
    env = os.environ.get("ARGOS_GITHUB_REPO", "").strip()
    if env:
        return env
    s = _read_settings_key("ARGOS_GITHUB_REPO")
    if s:
        return s
    return DEFAULT_GITHUB_REPO


def _version_from_tag(tag: str) -> str:
    m = _TAG_RE.match((tag or "").strip())
    return m.group(1) if m else (tag or "").lstrip("v")


def _api_request(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ArgosTranslate-Updater/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick_zip_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """选择程序更新 zip，排除 install_wheels / 安装包等非更新包。"""
    candidates: list[dict[str, Any]] = []
    for a in assets or []:
        name = (a.get("name") or "").strip()
        if not name.lower().endswith(".zip"):
            continue
        low = name.lower()
        if any(
            token in low
            for token in (
                "launcher",
                "setup",
                "install_wheels",
                "payload",
                "embed",
            )
        ):
            continue
        if name.startswith("ArgosTranslate-v") or name.startswith("ArgosTranslate-"):
            candidates.append(a)

    for a in candidates:
        name = (a.get("name") or "").strip()
        if re.fullmatch(r"ArgosTranslate-v\d+\.\d+\.\d+\.zip", name, re.I):
            return a
    for a in candidates:
        name = (a.get("name") or "").strip()
        if "install_wheels" not in name.lower():
            return a
    return None


def fetch_latest_release(
    repo: str | None = None,
    *,
    include_prerelease: bool = False,
) -> ReleaseInfo:
    repo = (repo or github_repo()).strip()
    url = _API_LATEST.format(repo=repo)
    try:
        data = _api_request(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"仓库未找到或未发布 Release：{repo}") from e
        raise RuntimeError(f"无法访问 GitHub（HTTP {e.code}）") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误，无法检查更新：{e.reason}") from e

    if data.get("draft"):
        raise RuntimeError("最新 Release 仍为草稿，暂不可更新。")
    if data.get("prerelease") and not include_prerelease:
        pass  # /latest 通常已是稳定版

    tag = str(data.get("tag_name") or "")
    version = _version_from_tag(tag)
    asset = _pick_zip_asset(data.get("assets") or [])
    if asset is None:
        raise RuntimeError(
            f"Release {tag} 中未找到程序更新 zip（ArgosTranslate-vX.Y.Z.zip）。"
        )
    return ReleaseInfo(
        tag=tag,
        version=version,
        name=str(data.get("name") or tag),
        html_url=str(data.get("html_url") or f"https://github.com/{repo}/releases"),
        body=str(data.get("body") or "").strip(),
        zip_url=str(asset.get("browser_download_url") or ""),
        zip_name=str(asset.get("name") or ""),
        zip_size=int(asset.get("size") or 0),
    )


def installed_version(install_root: Path | None = None) -> str:
    root = install_root or find_portable_root()
    if is_install_root(root):
        return read_installed_version(root)
    return read_version_json(root).get("version", APP_VERSION) or APP_VERSION


def check_for_update(install_root: Path | None = None) -> tuple[str, ReleaseInfo | None]:
    """
    返回 (状态说明, 若有新版本则 ReleaseInfo)。
    已是最新时 ReleaseInfo 仍返回远端信息便于展示。
    """
    root = install_root or find_portable_root()
    local = installed_version(root)
    release = fetch_latest_release()
    cmp = compare_versions(release.version, local)
    if cmp > 0:
        return (
            f"发现新版本 {release.version}（当前 {local}）",
            release,
        )
    return (f"当前已是最新版本（{local}）", release)


def _download(url: str, dest: Path, cb: ProgressCb | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ArgosTranslate-Updater/1.0"},
        method="GET",
    )

    def rep(block: int, block_size: int, total: int) -> None:
        if cb and total > 0 and block % 16 == 0:
            pct = min(100, int(block * block_size * 100 / total))
            cb(f"正在下载… {pct}%")

    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if cb and total > 0 and read % (1024 * 512) < len(chunk):
                    pct = min(100, int(read * 100 / total))
                    cb(f"正在下载… {pct}%")


def extract_update_zip(zip_path: Path, work_dir: Path) -> Path:
    """解压更新 zip，返回含 version.json 的 payload 根目录。"""
    extract_root = work_dir / "unzipped"
    if extract_root.exists():
        shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_root)

    if (extract_root / "version.json").is_file():
        return extract_root

    tops = [p for p in extract_root.iterdir() if p.is_dir()]
    if len(tops) == 1 and (tops[0] / "version.json").is_file():
        return tops[0]

    for vj in extract_root.rglob("version.json"):
        parent = vj.parent
        if (parent / "terminology_bridge.py").is_file() or (
            parent / "app_version.py"
        ).is_file():
            return parent

    for vj in extract_root.rglob("version.json"):
        return vj.parent

    raise RuntimeError("更新包格式无效：未找到 version.json。")


def download_and_apply_release(
    release: ReleaseInfo,
    install_root: Path | None = None,
    *,
    progress: ProgressCb | None = None,
    force: bool = False,
) -> tuple[int, list[str], str, str]:
    """
    下载并就地更新。返回 (文件数, 错误列表, 旧版本, 新版本)。
    """
    root = (install_root or find_portable_root()).resolve()
    if not is_install_root(root):
        raise RuntimeError("未找到有效安装目录，请先在「安装位置」完成安装。")

    old_ver = read_installed_version(root)
    if not force and compare_versions(release.version, old_ver) <= 0:
        raise RuntimeError(f"当前版本 {old_ver} 不低于 {release.version}，无需更新。")

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    work = Path(tempfile.mkdtemp(prefix="argos_update_"))
    try:
        zip_path = work / release.zip_name
        log(f"正在从 GitHub 下载 {release.zip_name}…")
        _download(release.zip_url, zip_path, progress)
        log("正在解压更新包…")
        payload = extract_update_zip(zip_path, work)
        log(f"正在安装到 {root}…")
        count, errors = apply_update(payload, root, on_progress=progress)
        new_ver = read_installed_version(root)
        return count, errors, old_ver, new_ver
    finally:
        shutil.rmtree(work, ignore_errors=True)
