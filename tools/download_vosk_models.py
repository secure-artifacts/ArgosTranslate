"""
下载 Vosk 离线语音识别模型到 data/vosk-models/。
用法（在 ArgosTranslate 根目录）：
  venv\\Scripts\\python.exe tools\\download_vosk_models.py
  venv\\Scripts\\python.exe tools\\download_vosk_models.py ru uk
  venv\\Scripts\\python.exe tools\\download_vosk_models.py ru uk --large
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import offline_speech as sp  # noqa: E402


def main() -> int:
    args = [a.strip().lower() for a in sys.argv[1:] if a.strip()]
    force_large = "--large" in args or "-l" in args
    codes = [a for a in args if not a.startswith("-")]
    if not codes:
        codes = ["ru", "uk"]
    ok_all = True
    for code in codes:
        print(f"=== {code} ===")
        cur = sp.resolve_model_dir(code)
        want = sp.model_dir_names_for_lang(code)[0]
        if cur is not None and not force_large:
            print(f"已安装：{cur}")
            print(f"（若要换更大模型，加参数 --large 重新下载 {want}）")
            continue
        if force_large and cur is not None:
            print(f"将下载更大模型：{want}（当前：{cur.name}）")

        def prog(m: str) -> None:
            print(m)

        ok, err = sp.download_model_for_lang(
            code, on_progress=prog, prefer_largest=True
        )
        if ok:
            print(f"完成：{sp.resolve_model_dir(code)}")
        else:
            print(f"失败：{err}")
            ok_all = False
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
