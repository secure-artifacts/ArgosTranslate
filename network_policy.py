"""下载与 pip 源策略：禁止中国大陆主机与镜像。"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

_PROXY_ENV_KEYS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "PIP_PROXY",
    "PIP_INDEX_URL",
)

_LOCALHOST_PROXY_RE = re.compile(
    r"(?:^|[/@])(?:127\.0\.0\.1|localhost|0\.0\.0\.0)(?::|\b)",
    re.IGNORECASE,
)

# 常见 PyPI 镜像（含 .com 域名但属大陆节点）
_FORBIDDEN_PIP_HOSTS: frozenset[str] = frozenset(
    {
        "pypi.tuna.tsinghua.edu.cn",
        "mirrors.aliyun.com",
        "mirrors.cloud.tencent.com",
        "mirrors.huaweicloud.com",
        "pypi.mirrors.ustc.edu.cn",
        "mirror.sjtu.edu.cn",
        "pypi.douban.com",
        "pypi.doubanio.com",
        "mirrors.163.com",
        "mirrors.bfsu.edu.cn",
        "mirrors.nju.edu.cn",
    }
)

# 默认 pip 源：官方 + 欧美社区镜像（非中国大陆）
DEFAULT_PIP_INDEXES: tuple[str, ...] = (
    "https://pypi.org/simple",
    "https://mirror.math.princeton.edu/pypi/web/simple",
    "https://mirrors.dotsrc.org/pypi/web/simple",
)


def pip_index_host(url: str) -> str:
    return urlparse(url.strip()).netloc.lower().split(":")[0]


def is_forbidden_mainland_china_host(url: str) -> bool:
    """判断 URL 是否指向禁止使用的主机（中国大陆 / .cn）。"""
    host = pip_index_host(url)
    if not host:
        return False
    if host == "cn" or host.endswith(".cn"):
        return True
    return host in _FORBIDDEN_PIP_HOSTS


def assert_allowed_pip_index(url: str) -> str:
    url = url.strip()
    if is_forbidden_mainland_china_host(url):
        raise RuntimeError(
            "禁止使用中国大陆 PyPI 镜像或 .cn 主机。\n"
            f"当前：{url}\n"
            "请留空以使用官方 pypi.org，或设置 ARGOS_PIP_INDEX_URL 为其他可用源。"
        )
    return url


def pip_index_attempts() -> list[str]:
    """pip 安装尝试顺序：可选自定义源 + 默认非大陆镜像列表。"""
    custom = os.environ.get("ARGOS_PIP_INDEX_URL", "").strip()
    seen: set[str] = set()
    attempts: list[str] = []
    if custom:
        attempts.append(assert_allowed_pip_index(custom))
        seen.add(custom.rstrip("/").lower())
    for url in DEFAULT_PIP_INDEXES:
        if is_forbidden_mainland_china_host(url):
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        attempts.append(url)
    return attempts


def assert_allowed_download_url(url: str) -> str:
    """安装程序联网下载（python.org、pypi 等）须通过策略校验。"""
    url = url.strip()
    if is_forbidden_mainland_china_host(url):
        raise RuntimeError(
            "禁止使用中国大陆下载地址。\n"
            f"当前：{url}"
        )
    return url


def _proxy_value_uses_localhost(value: str) -> bool:
    value = value.strip()
    if not value:
        return False
    if _LOCALHOST_PROXY_RE.search(value):
        return True
    try:
        host = urlparse(value).hostname or ""
    except Exception:
        host = ""
    return host.lower() in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def sanitized_install_environ(
    base: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """
    安装子进程用环境变量：移除指向本机端口的无效代理（常见于 Clash/V2Ray 未启动）。
    返回 (env, 已移除项说明)。
    """
    env = dict(base if base is not None else os.environ)
    if os.environ.get("ARGOS_INSTALL_USE_PROXY", "").strip() == "1":
        return env, []

    removed: list[str] = []
    for key in _PROXY_ENV_KEYS:
        val = env.get(key, "")
        if not val:
            continue
        if key == "PIP_INDEX_URL":
            if not os.environ.get("ARGOS_PIP_INDEX_URL", "").strip():
                removed.append(f"{key}={val}")
                env.pop(key, None)
            elif is_forbidden_mainland_china_host(val):
                removed.append(f"{key}={val}")
                env.pop(key, None)
            continue
        if _proxy_value_uses_localhost(val):
            removed.append(f"{key}={val}")
            env.pop(key, None)

    # 让 pip/urllib 直连 pypi.org，不走系统代理
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env, removed
