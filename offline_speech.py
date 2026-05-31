"""
完全离线语音识别（Vosk + 本地麦克风录音）。
- 音频与识别均在用户本机完成，不访问网络、不向第三方上传语音或文本。
- 需自行下载 Vosk 语言模型解压到 data/vosk-models/（见同目录 README.txt）。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlretrieve

from PyQt5.QtCore import QThread, pyqtSignal

from terminology_bridge import portable_root

MODELS_ROOT = portable_root() / "data" / "vosk-models"

# 官方 zip（解压后目录名须与 _LANG_MODEL_DIRS 一致）
_MODEL_ZIP_URL: dict[str, str] = {
    "vosk-model-small-cn-0.22": "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip",
    "vosk-model-small-en-us-0.15": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
    "vosk-model-small-ru-0.22": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
    "vosk-model-ru-0.22": "https://alphacephei.com/vosk/models/vosk-model-ru-0.22.zip",
    "vosk-model-ru-0.42": "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip",
    "vosk-model-small-uk-v3-nano": "https://alphacephei.com/vosk/models/vosk-model-small-uk-v3-nano.zip",
    "vosk-model-small-uk-v3-small": "https://alphacephei.com/vosk/models/vosk-model-small-uk-v3-small.zip",
    "vosk-model-uk-v3": "https://alphacephei.com/vosk/models/vosk-model-uk-v3.zip",
    "vosk-model-uk-v3-lgraph": "https://alphacephei.com/vosk/models/vosk-model-uk-v3-lgraph.zip",
}

# Argos 语言 code → 解压后的模型目录名（按优先级：靠前=更大/更准，已安装则自动选用）
_LANG_MODEL_DIRS: dict[str, tuple[str, ...]] = {
    "zh": ("vosk-model-small-cn-0.22", "vosk-model-cn-0.22"),
    "zt": ("vosk-model-small-cn-0.22", "vosk-model-cn-0.22"),
    "en": ("vosk-model-small-en-us-0.15", "vosk-model-en-us-0.22"),
    "ru": (
        "vosk-model-ru-0.42",
        "vosk-model-ru-0.22",
        "vosk-model-small-ru-0.22",
    ),
    "uk": (
        "vosk-model-uk-v3",
        "vosk-model-uk-v3-lgraph",
        "vosk-model-small-uk-v3-small",
        "vosk-model-small-uk-v3-nano",
    ),
    "de": ("vosk-model-small-de-0.15",),
    "fr": ("vosk-model-small-fr-0.22",),
    "es": ("vosk-model-small-es-0.22",),
    "ja": ("vosk-model-small-ja-0.22",),
    "ko": ("vosk-model-small-ko-0.22",),
}

BUTTON_TOOLTIP = (
    "离线语音识别：本机麦克风 + Vosk，不上传网络。"
    "点「语音开始」后边说边显示文字并自动翻译（类似谷歌翻译）；"
    "点「语音暂停」停止收音，点「语音继续」恢复。"
    "支持俄语、乌克兰语、中文（源语言选对应项）。"
    "可在下方选择输入/输出设备；立体声会自动混成单声道。"
    "模型在 data/vosk-models/（首次可自动下载）。"
)

AUDIO_PREFS_PATH = portable_root() / "data" / "config" / "speech_audio.json"


def models_root() -> Path:
    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    return MODELS_ROOT


def _is_valid_model_dir(p: Path) -> bool:
    if not p.is_dir():
        return False
    if (p / "am" / "final.mdl").is_file():
        return True
    if (p / "conf" / "model.conf").is_file():
        return True
    return False


def _resolve_model_path(p: Path) -> Path | None:
    """支持解压后多一层子目录（zip 内套同名文件夹）。"""
    if _is_valid_model_dir(p):
        return p
    if p.is_dir():
        for child in sorted(p.iterdir()):
            if child.is_dir() and _is_valid_model_dir(child):
                return child
    return None


def model_dir_names_for_lang(lang_code: str) -> tuple[str, ...]:
    code = (lang_code or "").strip().lower()
    return _LANG_MODEL_DIRS.get(
        code, _LANG_MODEL_DIRS.get("en", ("vosk-model-small-en-us-0.15",))
    )


def resolve_model_dir(lang_code: str, *, prefer_small: bool = False) -> Path | None:
    """prefer_small=True 时优先用小模型，语音会话加载更快。"""
    root = models_root()
    names = list(model_dir_names_for_lang(lang_code))
    if prefer_small:
        names = list(reversed(names))
    for n in names:
        found = _resolve_model_path(root / n)
        if found is not None:
            return found
    return None


def _download_zip(url: str, dest: Path, on_progress: Callable[[str], None] | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress(f"正在下载：{dest.name}")

    last_pct = [-1]

    def _hook(block: int, block_size: int, total: int) -> None:
        if not on_progress or total <= 0:
            return
        pct = min(100, int(100 * block * block_size / total))
        if pct != last_pct[0] and pct % 5 == 0:
            last_pct[0] = pct
            on_progress(f"下载中… {pct}%")

    urlretrieve(url, str(dest), _hook)


def download_model_for_lang(
    lang_code: str,
    on_progress: Callable[[str], None] | None = None,
    *,
    prefer_largest: bool = True,
) -> tuple[bool, str | None]:
    """
    为指定源语言下载并解压 Vosk 模型。返回 (成功, 错误信息)。
    prefer_largest=True 时下载列表中第一个（通常为最大/最准）未安装模型。
    """
    names = model_dir_names_for_lang(lang_code)
    if not names:
        return False, "未知语言代码"
    if resolve_model_dir(lang_code) is not None and not prefer_largest:
        return True, None
    name = ""
    if prefer_largest:
        for n in names:
            if _resolve_model_path(models_root() / n) is None and n in _MODEL_ZIP_URL:
                name = n
                break
        if not name:
            return True, None
    else:
        if resolve_model_dir(lang_code) is not None:
            return True, None
        name = names[0]
    url = _MODEL_ZIP_URL.get(name)
    if not url:
        return False, f"未配置模型下载地址：{name}"

    root = models_root()
    zip_path = root / f"{name}.zip"
    extract_root = root / name
    try:
        _download_zip(url, zip_path, on_progress)
        if on_progress:
            on_progress("正在解压模型…")
        if extract_root.exists():
            shutil.rmtree(extract_root, ignore_errors=True)
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_root)
        zip_path.unlink(missing_ok=True)
        inner = extract_root / name
        if inner.is_dir() and _is_valid_model_dir(inner):
            for item in inner.iterdir():
                dest = extract_root / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest, ignore_errors=True)
                    else:
                        dest.unlink(missing_ok=True)
                shutil.move(str(item), str(dest))
            shutil.rmtree(inner, ignore_errors=True)
        if resolve_model_dir(lang_code) is None:
            return False, f"解压后未找到有效模型文件，请检查：{extract_root}"
        if on_progress:
            on_progress("模型已就绪")
        return True, None
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        return False, f"下载或解压失败：{e}"


def audio_prefs_path() -> Path:
    return AUDIO_PREFS_PATH


def default_audio_prefs() -> dict[str, Any]:
    return {
        "input_device": None,
        "output_device": None,
        "input_device_name": "",
        "output_device_name": "",
        "channels": 1,
    }


def load_audio_prefs() -> dict[str, Any]:
    """读取录音设备偏好；channels 1=单声道，2=立体声。"""
    out = default_audio_prefs()
    path = audio_prefs_path()
    if not path.is_file():
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            if "input_device" in raw:
                v = raw["input_device"]
                out["input_device"] = int(v) if v is not None and v != "" else None
            if "output_device" in raw:
                v = raw["output_device"]
                out["output_device"] = int(v) if v is not None and v != "" else None
            ch = int(raw.get("channels") or 1)
            out["channels"] = 2 if ch >= 2 else 1
            for nk in ("input_device_name", "output_device_name"):
                if nk in raw:
                    out[nk] = str(raw.get(nk) or "").strip()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return out


def save_audio_prefs(prefs: dict[str, Any]) -> None:
    path = audio_prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = default_audio_prefs()
    if isinstance(prefs, dict):
        for k in list(data.keys()) + [
            "input_device_name",
            "output_device_name",
        ]:
            if k in prefs:
                data[k] = prefs[k]
    ch = int(data.get("channels") or 1)
    data["channels"] = 2 if ch >= 2 else 1
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


_AUX_DEVICE_RE = re.compile(
    r"Point\s*\d+|\bWave\s*\d+\b|Sound Mapper|Primary Sound|MIDI",
    re.IGNORECASE,
)


def _hostapi_index(hostapis: Any, needle: str) -> int | None:
    for i, h in enumerate(hostapis):
        if needle.lower() in str(h.get("name", "")).lower():
            return i
    return None


def _skip_device_name(name: str) -> bool:
    return bool(_AUX_DEVICE_RE.search(name))


def _collect_devices(
    devices: Any,
    hostapis: Any,
    *,
    kind: str,
    hostapi_idx: int | None,
) -> list[dict[str, Any]]:
    """与 Windows「声音」设置类似：仅 WASAPI，按设备名去重，隐藏多路虚拟端点。"""
    default = (
        "（系统默认输入）" if kind == "input" else "（系统默认输出）"
    )
    out: list[dict[str, Any]] = [
        {"index": None, "label": default, "max_channels": 2, "name": ""}
    ]
    seen: set[str] = set()
    for i, d in enumerate(devices):
        if hostapi_idx is not None and d.get("hostapi") != hostapi_idx:
            continue
        name = str(d.get("name") or "?").strip()
        if _skip_device_name(name):
            continue
        if kind == "input":
            ch = int(d.get("max_input_channels") or 0)
        else:
            ch = int(d.get("max_output_channels") or 0)
        if ch < 1:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "index": i,
                "label": name,
                "max_channels": ch,
                "name": name,
            }
        )
    return out


def resolve_input_device_index(prefs: dict[str, Any] | None) -> int | None:
    """按设备名解析 WASAPI 索引，避免旧版保存的 WDM 编号失效。"""
    p = prefs if isinstance(prefs, dict) else load_audio_prefs()
    inputs, _ = list_audio_devices()
    name = str(p.get("input_device_name") or "").strip()
    if name:
        for it in inputs:
            if it.get("name") == name or it.get("label") == name:
                return it.get("index")
    idx = p.get("input_device")
    if idx is not None:
        for it in inputs:
            if it.get("index") == idx:
                return idx
    return None


def list_audio_devices() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (输入设备列表, 输出设备列表)；列表与 Windows 声音设置中的设备名一致（WASAPI）。"""
    try:
        import sounddevice as sd
    except ImportError:
        return [], []
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return (
            [{"index": None, "label": "（系统默认输入）", "max_channels": 2}],
            [{"index": None, "label": "（系统默认输出）", "max_channels": 2}],
        )

    wasapi = _hostapi_index(hostapis, "WASAPI")
    inputs = _collect_devices(devices, hostapis, kind="input", hostapi_idx=wasapi)
    outputs = _collect_devices(devices, hostapis, kind="output", hostapi_idx=wasapi)

    # 极少数环境无 WASAPI：退回「每种设备名只保留一条」
    if len(inputs) <= 1 and len(outputs) <= 1:
        inputs = _collect_devices(devices, hostapis, kind="input", hostapi_idx=None)
        outputs = _collect_devices(devices, hostapis, kind="output", hostapi_idx=None)

    return inputs, outputs


def apply_audio_defaults(
    prefs: dict[str, Any] | None,
    *,
    input_only: bool = False,
) -> None:
    """将 sounddevice 默认设备设为所选；录音时建议 input_only=True，避免动输出导致虚拟声卡采样率异常。"""
    import sounddevice as sd

    p = prefs if isinstance(prefs, dict) else load_audio_prefs()
    inp = p.get("input_device")
    out = None if input_only else p.get("output_device")
    ddef = sd.default.device
    try:
        cur_in, cur_out = ddef[0], ddef[1]
    except (TypeError, IndexError):
        cur_in = cur_out = ddef
    if inp is not None and out is not None:
        sd.default.device = (int(inp), int(out))
    elif inp is not None:
        sd.default.device = (int(inp), cur_out)
    elif out is not None:
        sd.default.device = (cur_in, int(out))


def _wasapi_extra_settings(sd: Any, device_index: int | None) -> Any | None:
    if sys.platform != "win32":
        return None
    idx = _input_device_index(sd, device_index)
    if idx is None:
        return None
    try:
        hostapis = sd.query_hostapis()
        dev = sd.query_devices(idx)
        api = hostapis[int(dev["hostapi"])]["name"]
        if "WASAPI" in str(api).upper():
            return sd.WasapiSettings(exclusive=False)
    except Exception:
        pass
    return None


def _valid_record_configs(
    sd: Any,
    device_index: int | None,
    channels: int,
) -> list[tuple[int, int, Any | None]]:
    """用 check_input_settings 筛出设备真正支持的 (采样率, 声道, WASAPI 设置)。"""
    idx = _input_device_index(sd, device_index)
    ch_pref = max(1, int(channels))
    channel_tries = (1, ch_pref) if ch_pref > 1 else (ch_pref,)
    extras: list[Any | None] = []
    if sys.platform == "win32":
        try:
            extras.append(sd.WasapiSettings(exclusive=False))
        except Exception:
            pass
        try:
            extras.append(sd.WasapiSettings(exclusive=True))
        except Exception:
            pass
    if not extras:
        extras.append(None)
    out: list[tuple[int, int, Any | None]] = []
    seen: set[tuple[int, int, int]] = set()
    for try_ch in channel_tries:
        for rate in _samplerates_to_try(sd, device_index):
            for extra in extras:
                ex_id = id(extra)
                key = (rate, try_ch, ex_id)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    kwargs: dict[str, Any] = {
                        "channels": try_ch,
                        "samplerate": rate,
                        "dtype": "float32",
                    }
                    if idx is not None:
                        kwargs["device"] = idx
                    if extra is not None:
                        kwargs["extra_settings"] = extra
                    sd.check_input_settings(**kwargs)
                    out.append((rate, try_ch, extra))
                except Exception:
                    continue
    return out


def _record_via_input_stream(
    sd: Any,
    *,
    n_samples: int,
    rate: int,
    channels: int,
    device: int | None,
    extra: Any | None,
) -> Any:
    import numpy as np

    blocksize = max(256, min(4096, n_samples // 8 or 256))
    kwargs: dict[str, Any] = {
        "samplerate": rate,
        "channels": channels,
        "dtype": "float32",
        "blocksize": blocksize,
    }
    if device is not None:
        kwargs["device"] = device
    if extra is not None:
        kwargs["extra_settings"] = extra
    chunks: list[Any] = []
    with sd.InputStream(**kwargs) as stream:
        got = 0
        while got < n_samples:
            need = min(n_samples - got, blocksize)
            block, _overflow = stream.read(need)
            chunks.append(np.asarray(block, dtype=np.float32))
            got += len(chunks[-1])
    if not chunks:
        raise RuntimeError("未录到音频数据")
    return np.concatenate(chunks, axis=0)


def check_microphone_available(prefs: dict[str, Any] | None = None) -> str | None:
    """返回 None 表示可用，否则为错误说明。"""
    try:
        import sounddevice as sd
    except ImportError as e:
        return f"缺少依赖：{e}\n请执行：pip install vosk sounddevice numpy"
    p = prefs if isinstance(prefs, dict) else load_audio_prefs()
    try:
        apply_audio_defaults(p, input_only=True)
        devices = sd.query_devices()
        inp = resolve_input_device_index(p)
        if not devices:
            return "未检测到音频设备。"
        if inp is None:
            idx = sd.default.device[0]
        else:
            idx = int(inp)
        if idx is None or int(idx) < 0:
            return (
                "未设置录音设备。请在下方「输入设备」中选择麦克风，"
                "或在 Windows 声音设置中指定默认输入。"
            )
        dev = devices[int(idx)]
        need_ch = 2 if int(p.get("channels") or 1) >= 2 else 1
        if int(dev.get("max_input_channels") or 0) < need_ch:
            return (
                f"当前输入设备仅支持 {dev.get('max_input_channels')} 声道，"
                f"无法按立体声（2 声道）录音。请改选「单声道」或换设备。"
            )
    except Exception as e:
        return f"无法访问麦克风：{e}"
    return None


def is_model_installed(lang_code: str) -> bool:
    return resolve_model_dir(lang_code) is not None


def describe_setup(lang_code: str) -> str:
    """未检测到模型时，向用户展示说明与下载指引。"""
    root = models_root()
    names = model_dir_names_for_lang(lang_code)
    hint = names[0] if names else "vosk-model-small-ru-0.22"
    code = (lang_code or "").strip().lower()
    if code == "uk":
        size_hint = "约 325–345MB（大模型）"
    elif code == "ru":
        size_hint = "约 1.5–1.8GB（大模型，需足够磁盘与内存）"
    else:
        size_hint = "约 40MB 起"
    return (
        "未找到与当前「源语言」匹配的 Vosk 离线模型。\n\n"
        f"推荐模型目录名：{hint}\n"
        f"安装位置：{root}\n\n"
        f"可点击「是」由程序自动下载（{size_hint}，仅需一次，需联网）；\n"
        "或手动从 https://alphacephei.com/vosk/models 下载 zip 解压到上述目录。\n\n"
        "依赖（venv）：pip install vosk sounddevice numpy\n\n"
        "识别在本机完成，不上传语音。"
    )


VOSK_SAMPLE_RATE = 16000


def _float32_to_mono(wave_float: Any, channels: int) -> Any:
    """立体声时取左右声道平均，供 Vosk 单声道识别。"""
    import numpy as np

    a = np.asarray(wave_float, dtype=np.float32)
    if a.ndim == 1:
        return a.reshape(-1)
    if a.shape[1] >= 2 and int(channels) >= 2:
        return a[:, :2].mean(axis=1)
    return a[:, 0]


def _resample_mono_to_16k(mono: Any, src_rate: int) -> Any:
    """将单声道 float32 重采样到 16 kHz（Vosk 要求）。"""
    import numpy as np

    src = int(src_rate or VOSK_SAMPLE_RATE)
    if src == VOSK_SAMPLE_RATE:
        return mono
    w = np.asarray(mono, dtype=np.float32).reshape(-1)
    if w.size < 2:
        return w
    n_out = max(1, int(round(w.size * VOSK_SAMPLE_RATE / src)))
    x_old = np.arange(w.size, dtype=np.float64)
    x_new = np.linspace(0, w.size - 1, n_out, dtype=np.float64)
    return np.interp(x_new, x_old, w).astype(np.float32)


def _input_device_index(sd: Any, device_index: int | None) -> int | None:
    if device_index is not None:
        return int(device_index)
    try:
        ddef = sd.default.device
        idx = ddef[0] if isinstance(ddef, (list, tuple)) else ddef
        return int(idx) if idx is not None and int(idx) >= 0 else None
    except Exception:
        return None


def _samplerates_to_try(sd: Any, device_index: int | None) -> list[int]:
    """设备常用采样率；多数声卡/虚拟声卡不支持 16 kHz 直录。"""
    rates: list[int] = []
    idx = _input_device_index(sd, device_index)
    if idx is not None:
        try:
            dev = sd.query_devices(idx)
            dsr = int(float(dev.get("default_samplerate") or 0))
            if dsr > 0:
                rates.append(dsr)
        except Exception:
            pass
    # Voicemeeter 等虚拟声卡通常只接受 48000，勿把 44100/16000 放太前
    for r in (48000, 44100, 32000, 22050):
        if r not in rates:
            rates.append(r)
    if VOSK_SAMPLE_RATE not in rates:
        rates.append(VOSK_SAMPLE_RATE)
    return rates


def _pcm_from_float32_mono(
    wave_float: Any,
    channels: int = 1,
    *,
    recorded_rate: int = VOSK_SAMPLE_RATE,
) -> bytes:
    import numpy as np

    w = _float32_to_mono(wave_float, channels)
    w = _resample_mono_to_16k(w, recorded_rate)
    w = np.clip(w, -1.0, 1.0)
    return (w * 32767.0).astype("<i2").tobytes()


def record_audio_blocking(
    seconds: float,
    prefs: dict[str, Any] | None = None,
) -> tuple[Any, str | None, int]:
    """
    同步录音。返回 (float32 数组, 错误信息, 实际采样率)。
    先用设备默认/常见采样率录音，识别前在 _pcm_from_float32_mono 中转为 16 kHz。
    """
    try:
        import sounddevice as sd
    except ImportError as e:
        return None, f"缺少依赖：{e}\n请执行：pip install vosk sounddevice numpy", VOSK_SAMPLE_RATE

    p = prefs if isinstance(prefs, dict) else load_audio_prefs()
    ch = 2 if int(p.get("channels") or 1) >= 2 else 1
    dur = max(2.0, min(60.0, seconds))
    device = resolve_input_device_index(p)

    configs = _valid_record_configs(sd, device, ch)
    if not configs:
        configs = [(48000, 1, _wasapi_extra_settings(sd, device))]

    last_err: Exception | None = None
    for rate, try_ch, extra in configs:
        n_samples = int(dur * rate)
        for attempt in range(3):
            try:
                if attempt:
                    time.sleep(0.25 * attempt)
                audio = _record_via_input_stream(
                    sd,
                    n_samples=n_samples,
                    rate=rate,
                    channels=try_ch,
                    device=device,
                    extra=extra,
                )
                return audio, None, rate
            except Exception as e:
                last_err = e
                err_s = str(e).lower()
                if "9999" not in err_s and "busy" not in err_s and "490" not in err_s:
                    break
        continue

    hint = (
        f"录音失败（请检查设备、声道与麦克风权限）：{last_err}\n\n"
        "Voicemeeter 建议：\n"
        "1. Voicemeeter 采样率设为 48000；\n"
        "2. 输入选 B1，声道选「单声道」；\n"
        "3. 点「刷新设备」后重选 B1；\n"
        "4. 关闭占用麦克风的其他程序后重试。\n"
        "若刚更新过程序，请完全退出后重新打开。"
    )
    return None, hint, VOSK_SAMPLE_RATE


def record_mono_blocking(seconds: float) -> tuple[Any, str | None, int]:
    return record_audio_blocking(seconds, load_audio_prefs())


def _peak_amplitude(wave_float: Any, channels: int) -> float:
    import numpy as np

    a = np.asarray(wave_float, dtype=np.float32)
    if a.size == 0:
        return 0.0
    mono = _float32_to_mono(a, channels)
    return float(np.max(np.abs(mono)))


def recognize_pcm(pcm: bytes, model: Any) -> tuple[str, str | None]:
    from vosk import KaldiRecognizer

    if not pcm:
        return "", None
    rec = KaldiRecognizer(model, 16000)
    step = 4000
    partial = ""
    for i in range(0, len(pcm), step):
        if rec.AcceptWaveform(pcm[i : i + step]):
            try:
                res = json.loads(rec.Result())
                partial = (res.get("text") or "").strip() or partial
            except json.JSONDecodeError:
                pass
    try:
        res = json.loads(rec.FinalResult())
    except json.JSONDecodeError:
        return "", "识别结果解析失败"
    text = (res.get("text") or "").strip() or partial
    return text, None


def recognize_blocking(lang_code: str, seconds: float = 14.0) -> tuple[str, str | None]:
    """
    同步加载模型、录音并识别。返回 (文本, 错误信息)。
    """
    try:
        from vosk import Model, SetLogLevel
    except ImportError as e:
        return "", f"缺少依赖：{e}\n请执行：pip install vosk sounddevice numpy"

    SetLogLevel(-1)
    mdir = resolve_model_dir(lang_code)
    if mdir is None:
        return "", describe_setup(lang_code)

    try:
        model = Model(str(mdir))
    except Exception as e:
        return "", f"无法加载模型：{e}"

    audio, err, rate = record_audio_blocking(seconds, load_audio_prefs())
    if err or audio is None:
        return "", err or "录音失败"

    pcm = _pcm_from_float32_mono(
        audio,
        load_audio_prefs().get("channels", 1),
        recorded_rate=rate,
    )
    return recognize_pcm(pcm, model)


def _parse_vosk_text(payload: str, key: str) -> str:
    try:
        res = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    return (res.get(key) or "").strip()


def _pick_stream_config(
    sd: Any, device: int | None, ch_pref: int
) -> tuple[int, int, Any | None] | None:
    configs = _valid_record_configs(sd, device, ch_pref)
    if configs:
        return configs[0]
    extra = _wasapi_extra_settings(sd, device)
    return (48000, 1 if ch_pref > 1 else ch_pref, extra)


def _format_mic_open_error(exc: Exception) -> str:
    s = str(exc)
    low = s.lower()
    if "9999" in s or "490" in s or "wdm" in low or "wdmks" in low:
        return (
            "无法打开麦克风：设备可能被占用或声道/采样率不匹配。\n\n"
            "建议：\n"
            "1. 点「声音设置」，将「声道」改为「单声道」后再试；\n"
            "2. 确认 Voicemeeter 已运行且 B1 有信号；\n"
            "3. 关闭其他占用麦克风的程序（会议软件、浏览器等）。\n\n"
            f"技术信息：{s}"
        )
    return f"无法打开麦克风：{s}"


def _open_input_stream_with_retry(
    sd: Any,
    device: int | None,
    ch_pref: int,
    callback,
) -> tuple[Any, int, int] | tuple[None, None, None]:
    """
    尝试多种采样率/声道/WASAPI 组合打开 InputStream。
    成功返回 (stream, rate, channels)；失败返回 (None, None, None)。
    """
    import time

    configs = _valid_record_configs(sd, device, ch_pref)
    if not configs:
        extra = _wasapi_extra_settings(sd, device)
        configs = [(48000, 1, extra)]
    last_err: Exception | None = None
    blocksize = 4096
    for rate, channels, extra in configs:
        for attempt in range(3):
            try:
                if attempt:
                    time.sleep(0.25 * attempt)
                kwargs: dict[str, Any] = {
                    "samplerate": rate,
                    "channels": channels,
                    "dtype": "float32",
                    "blocksize": max(1024, int(rate * 0.08)),
                    "callback": callback,
                }
                if device is not None:
                    kwargs["device"] = device
                if extra is not None:
                    kwargs["extra_settings"] = extra
                stream = sd.InputStream(**kwargs)
                stream.start()
                return stream, rate, channels
            except Exception as e:
                last_err = e
                err_s = str(e).lower()
                if (
                    "9999" not in err_s
                    and "490" not in err_s
                    and "busy" not in err_s
                    and "wdm" not in err_s
                ):
                    break
    if last_err is not None:
        raise last_err
    raise RuntimeError("未找到可用的录音参数")


class StreamingOfflineSpeechSessionWorker(QThread):
    """
    流式语音：麦克风持续输入，边说边出 partial 文字，句末出 final；
    配合界面可实现类似谷歌翻译的「实时识别 + 自动翻译」。
    """

    partial_text = pyqtSignal(str)
    final_text = pyqtSignal(str)
    error_msg = pyqtSignal(str)
    status_msg = pyqtSignal(str)

    def __init__(
        self,
        lang_code: str,
        audio_prefs: dict[str, Any] | None = None,
    ):
        super().__init__()
        self._lang = lang_code
        self._audio = (
            dict(audio_prefs) if isinstance(audio_prefs, dict) else load_audio_prefs()
        )
        self._stop = threading.Event()
        self._allow_record = threading.Event()
        self._stream = None

    def pause_recording(self) -> None:
        self._allow_record.clear()

    def resume_recording(self) -> None:
        self._allow_record.set()

    def request_stop(self) -> None:
        self._stop.set()

    def is_recording_allowed(self) -> bool:
        return self._allow_record.is_set()

    def run(self) -> None:
        import queue

        import numpy as np

        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as e:
            self.error_msg.emit(f"缺少依赖：{e}\n请执行：pip install vosk sounddevice numpy")
            return

        SetLogLevel(-1)
        mdir = resolve_model_dir(self._lang, prefer_small=True)
        if mdir is None:
            self.error_msg.emit(describe_setup(self._lang))
            return

        self.status_msg.emit("正在加载语音模型…")
        try:
            model = Model(str(mdir))
        except Exception as e:
            self.error_msg.emit(f"无法加载模型：{e}")
            return

        device = resolve_input_device_index(self._audio)
        ch_pref = 2 if int(self._audio.get("channels") or 1) >= 2 else 1

        rec = KaldiRecognizer(model, VOSK_SAMPLE_RATE)
        rec.SetWords(False)

        audio_q: queue.Queue[Any] = queue.Queue(maxsize=256)
        stream_error: list[str] = []

        def _callback(indata, _frames, _time_info, status) -> None:
            if status:
                stream_error.append(str(status))
            try:
                audio_q.put_nowait(np.asarray(indata, dtype=np.float32).copy())
            except queue.Full:
                pass

        try:
            opened = _open_input_stream_with_retry(
                sd, device, ch_pref, _callback
            )
            self._stream, rate, channels = opened
        except Exception as e:
            self.error_msg.emit(_format_mic_open_error(e))
            return

        self.status_msg.emit("正在聆听…")
        buf16k = np.array([], dtype=np.float32)
        feed_samples = 4000

        try:
            while not self._stop.is_set():
                if not self._allow_record.is_set():
                    self.msleep(40)
                    continue
                if stream_error:
                    self.error_msg.emit(f"录音设备异常：{stream_error[0]}")
                    break
                try:
                    block = audio_q.get(timeout=0.08)
                except queue.Empty:
                    continue

                mono = _float32_to_mono(block, channels)
                if mono.size == 0:
                    continue
                if rate != VOSK_SAMPLE_RATE:
                    mono = _resample_mono_to_16k(mono, rate)
                buf16k = np.concatenate([buf16k, mono])
                while buf16k.size >= feed_samples:
                    chunk = buf16k[:feed_samples]
                    buf16k = buf16k[feed_samples:]
                    pcm = (np.clip(chunk, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
                    if rec.AcceptWaveform(pcm):
                        text = _parse_vosk_text(rec.Result(), "text")
                        if text:
                            self.final_text.emit(text)
                    else:
                        partial = _parse_vosk_text(rec.PartialResult(), "partial")
                        self.partial_text.emit(partial)
        finally:
            try:
                if self._stream is not None:
                    self._stream.stop()
                    self._stream.close()
            except Exception:
                pass
            self._stream = None
            try:
                tail = _parse_vosk_text(rec.FinalResult(), "text")
                if tail:
                    self.final_text.emit(tail)
            except Exception:
                pass


class OfflineSpeechSessionWorker(QThread):
    """
    长时间语音会话：未暂停时在后台循环「录音一小段 → 识别」；
    暂停时仅等待，不结束线程。清空原文与翻译逻辑无关，不影响本会话。
    模型只加载一次。关闭窗口时应调用 request_stop() 并 wait()。
    """

    result_text = pyqtSignal(str)
    error_msg = pyqtSignal(str)
    status_msg = pyqtSignal(str)

    def __init__(
        self,
        lang_code: str,
        chunk_seconds: float = 4.0,
        audio_prefs: dict[str, Any] | None = None,
    ):
        super().__init__()
        self._lang = lang_code
        self._chunk = chunk_seconds
        self._audio = (
            dict(audio_prefs) if isinstance(audio_prefs, dict) else load_audio_prefs()
        )
        self._stop = threading.Event()
        self._allow_record = threading.Event()

    def pause_recording(self) -> None:
        """暂停：当前这一段录完后不再开始下一段，直至 resume。"""
        self._allow_record.clear()

    def resume_recording(self) -> None:
        """继续/开始收音循环。"""
        self._allow_record.set()

    def request_stop(self) -> None:
        """结束会话并退出线程。"""
        self._stop.set()

    def is_recording_allowed(self) -> bool:
        return self._allow_record.is_set()

    def run(self) -> None:
        try:
            from vosk import Model, SetLogLevel
        except ImportError as e:
            self.error_msg.emit(f"缺少依赖：{e}\n请执行：pip install vosk sounddevice numpy")
            return

        SetLogLevel(-1)
        mdir = resolve_model_dir(self._lang, prefer_small=True)
        if mdir is None:
            self.error_msg.emit(describe_setup(self._lang))
            return

        model_name = mdir.name if mdir is not None else ""
        if "small" in model_name or "nano" in model_name:
            self.status_msg.emit("正在加载语音模型…")
        else:
            self.status_msg.emit("正在加载语音模型（大模型首次较慢，请稍候）…")
        try:
            model = Model(str(mdir))
        except Exception as e:
            self.error_msg.emit(f"无法加载模型：{e}")
            return

        self.status_msg.emit("语音就绪，正在聆听…")
        chunk_n = 0
        while not self._stop.is_set():
            while not self._allow_record.is_set() and not self._stop.is_set():
                self.msleep(50)
            if self._stop.is_set():
                break

            chunk_n += 1
            dur = self._chunk if chunk_n > 1 else min(self._chunk, 3.5)
            self.status_msg.emit(f"正在录音 {int(dur)} 秒…")
            audio, err, rate = record_audio_blocking(dur, self._audio)
            if self._stop.is_set():
                break
            if err or audio is None:
                self.error_msg.emit(err or "录音失败")
                break

            self.status_msg.emit("正在识别…")
            pcm = _pcm_from_float32_mono(
                audio,
                self._audio.get("channels", 1),
                recorded_rate=rate,
            )
            text, rec_err = recognize_pcm(pcm, model)
            if rec_err:
                self.error_msg.emit(rec_err)
                break
            if text:
                self.result_text.emit(text)
                self.status_msg.emit("语音暂停")
            else:
                peak = _peak_amplitude(audio, self._audio.get("channels", 1))
                if peak < 0.01:
                    self.status_msg.emit(
                        "音量过低：请对着麦克风说话，或检查 Voicemeeter 是否把声音送到 B1"
                    )
                else:
                    self.status_msg.emit("未识别到语音，请继续说话…")


class VoskModelDownloadWorker(QThread):
    """后台下载并解压 Vosk 模型。"""

    progress = pyqtSignal(str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, lang_code: str):
        super().__init__()
        self._lang = lang_code

    def run(self) -> None:
        ok, err = download_model_for_lang(
            self._lang, on_progress=lambda m: self.progress.emit(m)
        )
        if ok:
            self.finished_ok.emit()
        else:
            self.failed.emit(err or "下载失败")
