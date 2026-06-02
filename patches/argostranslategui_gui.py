import importlib.util
import json
import os
import sys
from enum import Enum
from typing import Any
from functools import partial
from pathlib import Path

from argostranslate import settings, utils
from argostranslate.utils import error, info

_argos_translate_mod = None
_argos_package_mod = None


def _get_argos_translate():
    """延迟加载 translate（会拉入 ctranslate2，约 3s）；首屏不阻塞。"""
    global _argos_translate_mod
    if _argos_translate_mod is None:
        from argostranslate import translate as _argos_translate_mod
    return _argos_translate_mod


def _reset_translation_engine_modules() -> None:
    """重试加载前清缓存；注意：DLL 初始化失败后通常仍需重启整个程序。"""
    global _argos_translate_mod
    _argos_translate_mod = None
    try:
        import argostranslate.translate as tr_mod

        tr_mod._ctr2_mod = None
        if hasattr(tr_mod, "get_installed_languages"):
            tr_mod.get_installed_languages.cache_clear()
    except Exception:
        pass


def _vcredist_already_handled() -> bool:
    mod = _import_vcredist_helper()
    if mod is not None and getattr(mod, "is_vcredist_x64_installed", None):
        try:
            if mod.is_vcredist_x64_installed():
                return True
        except Exception:
            pass
    return False


def _get_argos_package():
    global _argos_package_mod
    if _argos_package_mod is None:
        from argostranslate import package as _argos_package_mod
    return _argos_package_mod
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *


_terminology_bridge_mod = None
_glossary_editor_mod = None
_word_info_mod = None
_offline_speech_mod = None
_app_version_mod = None
_translation_history_mod = None
_word_notebook_mod = None
_bulk_text_mod = None
_translation_quality_mod = None

# ISO 639-1 及 Argos 扩展码（zt、pb）→ 下拉框中文名称
_LANG_CODE_ZH: dict[str, str] = json.loads(
    '{"aa":"阿法尔语","ab":"阿布哈兹语","ae":"阿维斯陀语","af":"南非荷兰语","ak":"阿坎语","am":"阿姆哈拉语","an":"阿拉贡语","ar":"阿拉伯语","as":"阿萨姆语","av":"阿瓦尔语","ay":"艾马拉语","az":"阿塞拜疆语","ba":"巴什基尔语","be":"白俄罗斯语","bg":"保加利亚语","bi":"比斯拉马语","bm":"班巴拉语","bn":"孟加拉语","bo":"藏语","br":"布列塔尼语","bs":"波斯尼亚语","ca":"加泰罗尼亚语","ce":"车臣语","ch":"查莫罗语","co":"科西嘉语","cr":"克里语","cs":"捷克语","cu":"古教会斯拉夫语","cv":"楚瓦什语","cy":"威尔士语","da":"丹麦语","de":"德语","dv":"迪维希语","dz":"宗卡语","ee":"埃维语","el":"希腊语","en":"英语","eo":"世界语","es":"西班牙语","et":"爱沙尼亚语","eu":"巴斯克语","fa":"波斯语","ff":"富拉尼语","fi":"芬兰语","fj":"斐济语","fo":"法罗语","fr":"法语","fy":"西弗里西亚语","ga":"爱尔兰语","gd":"苏格兰盖尔语","gl":"加利西亚语","gn":"瓜拉尼语","gu":"古吉拉特语","gv":"马恩语","ha":"豪萨语","he":"希伯来语","hi":"印地语","ho":"希里莫图语","hr":"克罗地亚语","ht":"海地克里奥尔语","hu":"匈牙利语","hy":"亚美尼亚语","hz":"赫雷罗语","ia":"国际语","id":"印尼语","ie":"西方国际语","ig":"伊博语","ii":"四川彝语","ik":"因纽皮雅特语","io":"伊多语","is":"冰岛语","it":"意大利语","iu":"因纽特语","ja":"日语","jv":"爪哇语","ka":"格鲁吉亚语","kg":"刚果语","ki":"基库尤语","kj":"宽亚玛语","kk":"哈萨克语","kl":"格陵兰语","km":"高棉语","kn":"卡纳达语","ko":"韩语","kr":"卡努里语","ks":"克什米尔语","ku":"库尔德语","kv":"科米语","kw":"康沃尔语","ky":"吉尔吉斯语","la":"拉丁语","lb":"卢森堡语","lg":"卢干达语","li":"林堡语","ln":"林加拉语","lo":"老挝语","lt":"立陶宛语","lu":"卢巴语","lv":"拉脱维亚语","mg":"马达加斯加语","mh":"马绍尔语","mi":"毛利语","mk":"马其顿语","ml":"马拉雅拉姆语","mn":"蒙古语","mr":"马拉地语","ms":"马来语","mt":"马耳他语","my":"缅甸语","na":"瑙鲁语","nb":"书面挪威语","nd":"北恩德贝莱语","ne":"尼泊尔语","ng":"恩敦加语","nl":"荷兰语","nn":"新挪威语","no":"挪威语","nr":"南恩德贝莱语","nv":"纳瓦霍语","ny":"尼昂加语","oc":"奥克语","oj":"奥吉布瓦语","or":"奥里亚语","os":"奥塞梯语","pa":"旁遮普语","pi":"巴利语","pl":"波兰语","ps":"普什图语","pt":"葡萄牙语","qu":"克丘亚语","rm":"罗曼什语","rn":"隆迪语","ro":"罗马尼亚语","ru":"俄语","rw":"卢旺达语","sa":"梵语","sc":"萨丁尼亚语","sd":"信德语","se":"北萨米语","sg":"桑戈语","si":"僧伽罗语","sk":"斯洛伐克语","sl":"斯洛文尼亚语","sm":"萨摩亚语","sn":"修纳语","so":"索马里语","sq":"阿尔巴尼亚语","sr":"塞尔维亚语","ss":"斯瓦蒂语","st":"塞索托语","su":"巽他语","sv":"瑞典语","sw":"斯瓦希里语","ta":"泰米尔语","te":"泰卢固语","tg":"塔吉克语","th":"泰语","ti":"提格雷语","tk":"土库曼语","tl":"他加禄语","tn":"茨瓦纳语","to":"汤加语","tr":"土耳其语","ts":"宗加语","tt":"鞑靼语","tw":"契维语","ty":"塔希提语","ug":"维吾尔语","uk":"乌克兰语","ur":"乌尔都语","uz":"乌兹别克语","ve":"文达语","vi":"越南语","vo":"沃拉普克语","wa":"瓦隆语","wo":"沃洛夫语","xh":"科萨语","yi":"意第绪语","yo":"约鲁巴语","za":"壮语","zh":"中文（简体）","zu":"祖鲁语","zt":"中文（繁体）","pb":"葡萄牙语（巴西）"}'
)

# 语言包 metadata 中的英文名称 → 中文（补全代码表未覆盖的写法）
_LANG_EN_NAME_ZH: dict[str, str] = {
    "English": "英语",
    "Chinese": "中文（简体）",
    "Chinese (traditional)": "中文（繁体）",
    "Russian": "俄语",
    "Albanian": "阿尔巴尼亚语",
    "Arabic": "阿拉伯语",
    "Azerbaijani": "阿塞拜疆语",
    "Basque": "巴斯克语",
    "Bengali": "孟加拉语",
    "Bulgarian": "保加利亚语",
    "Catalan": "加泰罗尼亚语",
    "Czech": "捷克语",
    "Danish": "丹麦语",
    "Dutch": "荷兰语",
    "Esperanto": "世界语",
    "Estonian": "爱沙尼亚语",
    "Finnish": "芬兰语",
    "French": "法语",
    "Galician": "加利西亚语",
    "German": "德语",
    "Greek": "希腊语",
    "Hebrew": "希伯来语",
    "Hindi": "印地语",
    "Hungarian": "匈牙利语",
    "Indonesian": "印尼语",
    "Irish": "爱尔兰语",
    "Italian": "意大利语",
    "Japanese": "日语",
    "Korean": "韩语",
    "Kyrgyz": "吉尔吉斯语",
    "Latvian": "拉脱维亚语",
    "Lithuanian": "立陶宛语",
    "Malay": "马来语",
    "Norwegian": "挪威语",
    "Persian": "波斯语",
    "Polish": "波兰语",
    "Portuguese": "葡萄牙语",
    "Portuguese (Brazil)": "葡萄牙语（巴西）",
    "Romanian": "罗马尼亚语",
    "Slovak": "斯洛伐克语",
    "Slovenian": "斯洛文尼亚语",
    "Spanish": "西班牙语",
    "Swedish": "瑞典语",
    "Tagalog": "他加禄语",
    "Thai": "泰语",
    "Turkish": "土耳其语",
    "Ukrainian": "乌克兰语",
    "Ukranian": "乌克兰语",
    "Urdu": "乌尔都语",
    "Vietnamese": "越南语",
}


def _lang_combo_label_zh(lang) -> str:
    """语言下拉框显示用中文名（与 translate.Language 内部 code 一致，仅改展示）。"""
    code = (lang.code or "").strip().lower()
    if code in _LANG_CODE_ZH:
        return _LANG_CODE_ZH[code]
    name = (lang.name or "").strip()
    if name in _LANG_EN_NAME_ZH:
        return _LANG_EN_NAME_ZH[name]
    key = name.casefold()
    for en, zh in _LANG_EN_NAME_ZH.items():
        if en.casefold() == key:
            return zh
    return name


def _lang_index_first_matching_code(languages: list, codes: tuple[str, ...]) -> int | None:
    for want in codes:
        w = want.lower()
        for i, lang in enumerate(languages):
            if (lang.code or "").lower() == w:
                return i
    return None


def _is_zh_family_source(code: str | None) -> bool:
    """简体 / 繁体等：启用中文预处理与术语库（与 terminology_bridge.is_chinese_source_language 对齐）。"""
    c = (code or "").strip().lower()
    if c in ("zh", "zt", "zho"):
        return True
    return c.startswith("zh-") or c.startswith("zh_")


def _portable_bundle_root() -> Path | None:
    """向上查找含 terminology_bridge.py 或 portable_ui_theme.py 的目录（便携版 ArgosTranslate 根）。"""
    here = Path(__file__).resolve()
    for i in range(2, 10):
        try:
            root = here.parents[i]
        except IndexError:
            break
        if (root / "terminology_bridge.py").is_file():
            return root
        if (root / "portable_ui_theme.py").is_file():
            return root
    return None


def _prepare_native_dll(root: Path | None) -> None:
    if root is None:
        return
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from native_dll_bootstrap import prepare_native_dll_paths, preload_torch_dlls

        prepare_native_dll_paths(root)
        preload_torch_dlls(root)
    except Exception:
        boot = root / "native_dll_bootstrap.py"
        if boot.is_file():
            try:
                spec = importlib.util.spec_from_file_location(
                    "native_dll_bootstrap", boot
                )
                if spec is not None and spec.loader is not None:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.prepare_native_dll_paths(root)
                    if hasattr(mod, "preload_torch_dlls"):
                        mod.preload_torch_dlls(root)
            except Exception:
                pass


def _import_language_catalog_module():
    root = _portable_bundle_root()
    if root is None:
        return None
    path = root / "language_catalog.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("language_catalog", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_languages_lightweight(root: Path) -> list:
    mod = _import_language_catalog_module()
    if mod is None:
        return []
    return mod.load_languages_lightweight(root)


_vcredist_helper_mod = None


def _import_vcredist_helper():
    global _vcredist_helper_mod
    if _vcredist_helper_mod is False:
        return None
    if _vcredist_helper_mod is not None:
        return _vcredist_helper_mod
    root = _portable_bundle_root()
    if root is None:
        _vcredist_helper_mod = False
        return None
    path = root / "vcredist_helper.py"
    if not path.is_file():
        _vcredist_helper_mod = False
        return None
    spec = importlib.util.spec_from_file_location("vcredist_helper", path)
    if spec is None or spec.loader is None:
        _vcredist_helper_mod = False
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _vcredist_helper_mod = mod
    return mod


def _is_torch_dll_init_error(message: str) -> bool:
    mod = _import_vcredist_helper()
    if mod is not None and hasattr(mod, "is_torch_dll_init_error"):
        return bool(mod.is_torch_dll_init_error(message))
    m = (message or "").lower()
    return "1114" in message or "c10.dll" in m


def _dll_load_hint(err: str) -> str:
    if _is_torch_dll_init_error(err):
        return err + "\n\n（程序将提示从 Microsoft 官方源自动下载并安装 VC++ 2015-2022 x64 运行库。）"
    return err


def _portable_app_icon_path() -> Path | None:
    """便携版 assets/app_icon.ico（或 .png）— 窗口与任务栏图标。"""
    root = _portable_bundle_root()
    if root is None:
        return None
    assets = root / "assets"
    for name in ("app_icon.ico", "app_icon.png"):
        p = assets / name
        if p.is_file():
            return p
    return None


_WINDOWS_APP_USER_MODEL_ID = "ArgosTranslate.Portable.LocalTranslator.1"


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            _WINDOWS_APP_USER_MODEL_ID
        )
    except Exception:
        pass


def _apply_windows_taskbar_icon(widget) -> None:
    """pythonw 启动时任务栏常显示白纸图标；用 Win32 为窗口单独设置 .ico。"""
    if sys.platform != "win32":
        return
    pip = _portable_app_icon_path()
    if pip is None or not pip.suffix.lower() == ".ico":
        return
    try:
        import ctypes
        from ctypes import wintypes

        path = str(pip.resolve())
        user32 = ctypes.windll.user32
        LR_LOADFROMFILE = 0x10
        LR_DEFAULTSIZE = 0x40
        IMAGE_ICON = 1
        hwnd = wintypes.HWND(int(widget.winId()))
        if not hwnd:
            return
        hicon = user32.LoadImageW(
            None,
            path,
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not hicon:
            for size in (32, 16):
                hicon = user32.LoadImageW(
                    None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE
                )
                if hicon:
                    break
        if hicon:
            WM_SETICON = 0x80
            ICON_SMALL = 0
            ICON_BIG = 1
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
    except Exception as e:
        info(f"taskbar icon: {e}")


def _get_terminology_bridge():
    """便携版 ArgosTranslate 根目录下的 terminology_bridge.py；不存在则禁用术语库。"""
    global _terminology_bridge_mod
    if _terminology_bridge_mod is False:
        return None
    if _terminology_bridge_mod is not None:
        return _terminology_bridge_mod
    root = _portable_bundle_root()
    if root is None:
        _terminology_bridge_mod = False
        return None
    bridge = root / "terminology_bridge.py"
    if not bridge.is_file():
        _terminology_bridge_mod = False
        return None
    spec = importlib.util.spec_from_file_location("terminology_bridge", bridge)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _terminology_bridge_mod = mod
    return mod


def _import_glossary_editor_module():
    global _glossary_editor_mod
    if _glossary_editor_mod is False:
        return None
    if _glossary_editor_mod is not None:
        return _glossary_editor_mod
    root = _portable_bundle_root()
    if root is None:
        _glossary_editor_mod = False
        return None
    path = root / "glossary_editor.py"
    if not path.is_file():
        _glossary_editor_mod = False
        return None
    spec = importlib.util.spec_from_file_location("glossary_editor", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _glossary_editor_mod = mod
    return mod


def _import_word_info_module():
    global _word_info_mod
    if _word_info_mod is False:
        return None
    if _word_info_mod is not None:
        return _word_info_mod
    root = _portable_bundle_root()
    if root is None:
        _word_info_mod = False
        return None
    path = root / "word_info_dialog.py"
    if not path.is_file():
        _word_info_mod = False
        return None
    spec = importlib.util.spec_from_file_location("word_info_dialog", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _word_info_mod = mod
    return mod


def _import_app_version_module():
    global _app_version_mod
    if _app_version_mod is False:
        return None
    if _app_version_mod is not None:
        return _app_version_mod
    root = _portable_bundle_root()
    if root is None:
        _app_version_mod = False
        return None
    path = root / "app_version.py"
    if not path.is_file():
        _app_version_mod = False
        return None
    spec = importlib.util.spec_from_file_location("app_version", path)
    if spec is None or spec.loader is None:
        _app_version_mod = False
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _app_version_mod = mod
    return mod


def _app_display_name() -> str:
    ver_mod = _import_app_version_module()
    if ver_mod is not None:
        name = str(getattr(ver_mod, "APP_NAME", "") or "").strip()
        if name:
            return name
    return "本地翻译器（俄乌）"


def _import_offline_speech_module():
    global _offline_speech_mod
    if _offline_speech_mod is False:
        return None
    if _offline_speech_mod is not None:
        return _offline_speech_mod
    root = _portable_bundle_root()
    if root is None:
        _offline_speech_mod = False
        return None
    path = root / "offline_speech.py"
    if not path.is_file():
        _offline_speech_mod = False
        return None
    spec = importlib.util.spec_from_file_location("offline_speech", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _offline_speech_mod = mod
    return mod


def _import_translation_history_module():
    global _translation_history_mod
    if _translation_history_mod is False:
        return None
    if _translation_history_mod is not None:
        return _translation_history_mod
    root = _portable_bundle_root()
    if root is None:
        _translation_history_mod = False
        return None
    path = root / "translation_history.py"
    if not path.is_file():
        _translation_history_mod = False
        return None
    spec = importlib.util.spec_from_file_location("translation_history", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _translation_history_mod = mod
    return mod


def _import_word_notebook_module():
    global _word_notebook_mod
    if _word_notebook_mod is False:
        return None
    if _word_notebook_mod is not None:
        return _word_notebook_mod
    root = _portable_bundle_root()
    if root is None:
        _word_notebook_mod = False
        return None
    path = root / "word_notebook_dialog.py"
    if not path.is_file():
        _word_notebook_mod = False
        return None
    spec = importlib.util.spec_from_file_location("word_notebook_dialog", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _word_notebook_mod = mod
    return mod


def _import_bulk_text_module():
    global _bulk_text_mod
    if _bulk_text_mod is False:
        return None
    if _bulk_text_mod is not None:
        return _bulk_text_mod
    root = _portable_bundle_root()
    if root is None:
        _bulk_text_mod = False
        return None
    path = root / "bulk_text.py"
    if not path.is_file():
        _bulk_text_mod = False
        return None
    spec = importlib.util.spec_from_file_location("bulk_text", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _bulk_text_mod = mod
    return mod


def _import_translation_quality_module():
    global _translation_quality_mod
    if _translation_quality_mod is False:
        return None
    if _translation_quality_mod is not None:
        return _translation_quality_mod
    root = _portable_bundle_root()
    if root is None:
        _translation_quality_mod = False
        return None
    path = root / "translation_quality.py"
    if not path.is_file():
        _translation_quality_mod = False
        return None
    spec = importlib.util.spec_from_file_location("translation_quality", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _translation_quality_mod = mod
    return mod


def _try_apply_portable_ui_theme(app) -> None:
    """便携版根目录下的 portable_ui_theme.py（路径必须与 terminology_bridge 一致）。"""
    root = _portable_bundle_root()
    if root is None:
        return
    theme = root / "portable_ui_theme.py"
    if not theme.is_file():
        return
    try:
        spec = importlib.util.spec_from_file_location("portable_ui_theme", theme)
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.apply_application_theme(app, portable_root=root)
    except Exception as e:
        info(f"portable_ui_theme skipped: {e}")


class WorkerThread(QThread):
    """Runs a bound function on a thread"""

    def __init__(self, bound_worker_function):
        """Args:
        bound_worker_function (functools.partial)
        """
        super().__init__()
        self.bound_worker_function = bound_worker_function
        self.finished.connect(self.deleteLater)

    def run(self):
        self.bound_worker_function()


def _fast_startup_enabled() -> bool:
    return os.environ.get("ARGOS_FAST_STARTUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class LanguageLoadWorker(QThread):
    """后台扫描已安装语言包，避免阻塞首屏显示。"""

    finished_ok = pyqtSignal(object, bool)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_full_error = ""

    def run(self) -> None:
        root = _portable_bundle_root()
        if root is not None and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        full_err = ""
        if root is not None:
            _prepare_native_dll(root)
        try:
            langs = _get_argos_translate().get_installed_languages()
            if langs:
                self.finished_ok.emit(langs, False)
                return
        except Exception as e:
            full_err = _dll_load_hint(str(e))
        if root is not None:
            try:
                langs = _load_languages_lightweight(root)
                if langs:
                    self._last_full_error = full_err
                    self.finished_ok.emit(langs, True)
                    return
            except Exception:
                pass
        if full_err:
            self.failed.emit(full_err)
        else:
            self.failed.emit("未在 data\\local 下找到可用的语言包 metadata。")


class VcredistInstallWorker(QThread):
    """后台下载并安装 Microsoft VC++ 2015-2022 x64（官方全球 CDN）。"""

    status = pyqtSignal(str)
    finished_result = pyqtSignal(bool, str)

    def __init__(self, portable_root: Path, parent=None):
        super().__init__(parent)
        self._portable_root = portable_root

    def run(self) -> None:
        mod = _import_vcredist_helper()
        if mod is None:
            self.finished_result.emit(False, "未找到 vcredist_helper.py。")
            return
        try:
            ok, msg = mod.download_and_install_vcredist_x64(
                self._portable_root,
                status_cb=lambda s: self.status.emit(s),
            )
            self.finished_result.emit(ok, msg)
        except Exception as e:
            self.finished_result.emit(False, str(e))


class TranslationThread(QThread):
    send_text_update = pyqtSignal(str)

    def __init__(self, translation_function, show_loading_message):
        super().__init__()
        self.translation_function = translation_function
        self.show_loading_message = show_loading_message

    def run(self):
        from argostranslate.utils import error as at_error

        try:
            if self.show_loading_message:
                self.send_text_update.emit("正在翻译…")
            translated_text = self.translation_function()
            self.send_text_update.emit(translated_text)
        except Exception as e:
            at_error("Translation failed:", e)
            self.send_text_update.emit(
                "[翻译过程出错]\n"
                f"{type(e).__name__}: {e}\n\n"
                "可尝试：适当插入换行分段、稍后再试，或检查本机内存与语言包是否完整。"
            )


class WorkerStatusButton(QPushButton):
    class Status(Enum):
        NOT_STARTED = 0
        RUNNING = 1
        DONE = 2

    def __init__(self, text, bound_worker_function):
        super().__init__(text)
        self.text = text
        self.bound_worker_function = bound_worker_function
        self.clicked.connect(self.clicked_handler)
        self.set_status(self.Status.NOT_STARTED)

    def clicked_handler(self):
        info("WorkerStatusButton clicked_handler")
        if self.status == self.Status.NOT_STARTED:
            self.worker_thread = WorkerThread(self.bound_worker_function)
            self.worker_thread.finished.connect(self.finished_handler)
            self.set_status(self.Status.RUNNING)
            self.worker_thread.start()

    def finished_handler(self):
        info("WorkerStatusButton finished_handler")
        self.set_status(self.Status.DONE)

    def set_status(self, status):
        self.status = status
        if self.status == self.Status.NOT_STARTED:
            self.setText(self.text)
        elif self.status == self.Status.RUNNING:
            self.setText("⌛")
        elif self.status == self.Status.DONE:
            self.setText("✓")


class PackagesTable(QTableWidget):
    packages_changed = pyqtSignal()

    class TableContent(Enum):
        INSTALLED = 0
        AVAILABLE = 1

    class AvailableActions(Enum):
        UNINSTALL = 0
        INSTALL = 1

    def __init__(self, table_content, available_actions):
        super().__init__()
        self.table_content = table_content
        self.available_actions = available_actions

        self.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        headers = ["说明", "名称", "包名", "源语言代码", "目标语言代码", "版本"]
        if self.AvailableActions.UNINSTALL in self.available_actions:
            headers.append("卸载")
        if self.AvailableActions.INSTALL in self.available_actions:
            headers.append("安装")
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        # Padding in header sections used as workaround for inaccurate results of resizeColumnsToContents()
        self.STRETCH_COLUMN_MIN_PADDING = 50
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft)

        self.installed_packages = _get_argos_package().get_installed_packages()

    def get_packages(self):
        pkg = _get_argos_package()
        if self.table_content == self.TableContent.AVAILABLE:
            pkg.update_package_index()
            packages = pkg.get_available_packages()
        elif self.table_content == self.TableContent.INSTALLED:
            packages = pkg.get_installed_packages()
        else:
            raise Exception("Invalid table content")

        # Filter sbd packages in GUI
        packages = list(filter(lambda x: x.type != "sbd", packages))

        return packages

    def populate(self):
        packages = self.get_packages()

        self.setRowCount(len(packages))
        for i, pkg in enumerate(packages):
            name = str(pkg)
            package_name = _get_argos_package().argospm_package_name(pkg)
            package_version = pkg.package_version
            from_code = pkg.from_code
            to_code = pkg.to_code
            pkg = packages[i]
            readme_button = QPushButton("查看")
            bound_view_package_readme_function = partial(self.view_package_readme, pkg)
            readme_button.clicked.connect(bound_view_package_readme_function)
            row_index = 0
            self.setCellWidget(i, row_index, readme_button)
            row_index += 1
            self.setItem(i, row_index, QTableWidgetItem(name))
            row_index += 1
            self.setItem(i, row_index, QTableWidgetItem(package_name))
            row_index += 1
            self.setItem(i, row_index, QTableWidgetItem(from_code))
            row_index += 1
            self.setItem(i, row_index, QTableWidgetItem(to_code))
            row_index += 1
            self.setItem(i, row_index, QTableWidgetItem(package_version))
            row_index += 1
            if self.AvailableActions.UNINSTALL in self.available_actions:
                uninstall_button = QPushButton("🗑")
                bound_uninstall_function = partial(
                    PackagesTable.uninstall_package, self, pkg
                )
                uninstall_button.clicked.connect(bound_uninstall_function)
                self.setCellWidget(i, row_index, uninstall_button)
                row_index += 1
            if self.AvailableActions.INSTALL in self.available_actions:
                if pkg not in self.installed_packages:
                    bound_install_function = partial(
                        PackagesTable.install_package, self, pkg
                    )
                    install_button = WorkerStatusButton("⬇", bound_install_function)
                    self.setCellWidget(i, row_index, install_button)
                else:
                    self.setItem(i, row_index, QTableWidgetItem("已安装"))
                row_index += 1
        # Resize table widget
        self.setMinimumSize(QSize(0, 0))
        self.resizeColumnsToContents()
        self.adjustSize()
        # Set minimum width of packages_table that also limits size of packages window
        header_width = self.horizontalHeader().length()
        self.setMinimumSize(
            QSize(header_width + self.STRETCH_COLUMN_MIN_PADDING * 2, 0)
        )

    def uninstall_package(self, pkg):
        try:
            _get_argos_package().uninstall(pkg)
        except OSError as e:
            # packages included in a snap archive are on a
            # read-only filesystem and can't be deleted
            if "SNAP" in os.environ:
                error_message_box = QMessageBox()
                error_message_box.setWindowTitle("错误")
                error_message_box.setText(
                    "删除语言包时出错：\n"
                    + "Snap 归档中预装的包无法删除。"
                )
                error_message_box.setIcon(QMessageBox.Warning)
                error_message_box.exec_()
            else:
                raise e
        self.packages_changed.emit()
        self.populate()
        self.packages_changed.emit()

    def install_package(self, pkg):
        download_path = pkg.download()
        _get_argos_package().install_from_path(download_path)
        os.remove(download_path)
        self.packages_changed.emit()

    def view_package_readme(self, pkg):
        about_message_box = QMessageBox()
        about_message_box.setWindowTitle(str(pkg))
        about_message_box.setText(pkg.get_description())
        about_message_box.setIcon(QMessageBox.Information)
        about_message_box.exec_()


class ManagePackagesWindow(QWidget):
    packages_changed = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.packages_table = PackagesTable(
            PackagesTable.TableContent.INSTALLED,
            [PackagesTable.AvailableActions.UNINSTALL],
        )

        # Download packages
        def open_download_packages_view(self):
            self.download_packages_window = DownloadPackagesWindow()
            self.download_packages_window.packages_changed.connect(
                partial(PackagesTable.populate, self.packages_table)
            )
            self.download_packages_window.show()
            self.download_packages_window.packages_changed.connect(
                self.packages_changed.emit
            )

        self.download_packages_button = QPushButton("下载语言包")
        self.download_packages_button.clicked.connect(
            partial(open_download_packages_view, self)
        )

        # Install from file
        self.install_package_file_button = QPushButton("从文件安装语言包")
        self.install_package_file_button.clicked.connect(self.add_packages)

        # Add packages row
        self.add_packages_row_layout = QHBoxLayout()
        self.add_packages_row_layout.addWidget(self.download_packages_button)
        self.add_packages_row_layout.addWidget(self.install_package_file_button)
        self.add_packages_row_layout.addStretch()

        # Packages table
        self.packages_table.packages_changed.connect(self.packages_changed.emit)
        self.packages_table.populate()
        self.packages_layout = QVBoxLayout()
        self.packages_layout.addWidget(self.packages_table)

        # Layout
        self.layout = QVBoxLayout()
        self.layout.addLayout(self.add_packages_row_layout)
        self.layout.addLayout(self.packages_layout)
        self.layout.addStretch()
        self.setLayout(self.layout)

    def add_packages(self):
        file_dialog = QFileDialog()
        filepaths = file_dialog.getOpenFileNames(
            self,
            "选择 .argosmodel 语言包文件",
            str(Path.home()),
            "Argos 模型 (*.argosmodel)",
        )[0]
        if len(filepaths) > 0:
            for file_path in filepaths:
                _get_argos_package().install_from_path(file_path)
            self.packages_changed.emit()
            self.packages_table.populate()


class DownloadPackagesWindow(QWidget):
    packages_changed = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Update package definitions from remote
        pkg = _get_argos_package()
        pkg.update_package_index()

        # Load available packages from local package index
        available_packages = pkg.get_available_packages()

        # Packages table
        self.packages_table = PackagesTable(
            PackagesTable.TableContent.AVAILABLE,
            [PackagesTable.AvailableActions.INSTALL],
        )
        self.packages_table.packages_changed.connect(self.packages_changed.emit)
        self.packages_table.populate()
        self.packages_layout = QVBoxLayout()
        self.packages_layout.addWidget(self.packages_table)

        # Layout
        self.layout = QVBoxLayout()
        self.layout.addLayout(self.packages_layout)
        self.layout.addStretch()
        self.setLayout(self.layout)


class TranslationHistoryDialog(QDialog):
    """本地保存的翻译快照列表（语音会话中清空原文时写入）。"""

    def __init__(self, parent, items: list):
        super().__init__(parent)
        self.setWindowTitle("翻译历史")
        self.resize(920, 540)
        self._items = list(items)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "在离线语音会话进行中，若点击左侧「清空」，会将当时的原文与译文各保存一条到本列表（仅保存在本机 data/config/translation_history.json）。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "语言对", "原文", "译文"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        for it in self._items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(it.get("ts", ""))))
            pair = f"{it.get('src_lang_label', '')} → {it.get('tgt_lang_label', '')}"
            self.table.setItem(r, 1, QTableWidgetItem(pair))
            src = it.get("source") or ""
            tgt = it.get("target") or ""

            def trunc(s: str, n: int = 240) -> str:
                one = s.replace("\n", " ↵ ")
                return one if len(one) <= n else one[: n - 1] + "…"

            c2 = QTableWidgetItem(trunc(src))
            c2.setToolTip(src[:4000] + ("…" if len(src) > 4000 else ""))
            self.table.setItem(r, 2, c2)
            c3 = QTableWidgetItem(trunc(tgt))
            c3.setToolTip(tgt[:4000] + ("…" if len(tgt) > 4000 else ""))
            self.table.setItem(r, 3, c3)
        layout.addWidget(self.table)
        btn_row = QHBoxLayout()
        copy_btn = QPushButton("复制所选行（原文+译文）")
        copy_btn.clicked.connect(self._copy_selected)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _copy_selected(self) -> None:
        r = self.table.currentRow()
        if r < 0 or r >= len(self._items):
            QMessageBox.information(self, "翻译历史", "请先选中一行。")
            return
        it = self._items[r]
        src = it.get("source") or ""
        tgt = it.get("target") or ""
        QApplication.clipboard().setText(f"{src}\n---\n{tgt}")


_translation_tab_page_cls = None


def _get_ui_session_module():
    root = _portable_bundle_root()
    if root is None:
        return None
    path = root / "ui_session.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ui_session", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _get_translation_tab_page_class():
    global _translation_tab_page_cls
    if _translation_tab_page_cls is not None:
        return _translation_tab_page_cls
    root = _portable_bundle_root()
    if root is None:
        return None
    path = root / "translation_tab_page.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("translation_tab_page", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _translation_tab_page_cls = mod.TranslationTabPage
    return _translation_tab_page_cls


class GUIWindow(QMainWindow):
    def showEvent(self, event):
        super().showEvent(event)
        if _fast_startup_enabled() and self._portable_root is not None:
            if not getattr(self, "_taskbar_icon_scheduled", False):
                self._taskbar_icon_scheduled = True
                QTimer.singleShot(0, lambda: _apply_windows_taskbar_icon(self))
        else:
            _apply_windows_taskbar_icon(self)

    def __init__(self):
        super().__init__()

        self._portable_root = _portable_bundle_root()
        self._offline_speech_intro_shown = False
        self.languages = []
        self._languages_lightweight = False
        self._lang_load_full_error = ""
        self._lang_load_worker = None
        self._vcredist_worker = None
        self._vcredist_progress = None
        self._vcredist_install_done = False
        self._glossary_editor_dialog = None
        self._word_notebook_dialog = None
        self._deferred_tab_sessions: list = []
        self._deferred_active_tab = 0
        self._tabs = []
        self._tab_serial = 0
        self._tab_cls = _get_translation_tab_page_class()
        self._ui_session_mod = _get_ui_session_module()
        self._session_restore = None
        if self._portable_root is not None and self._ui_session_mod is not None:
            self._session_restore = self._ui_session_mod.load_session(
                self._portable_root
            )

        # Menu（便携版顶栏按钮替代后隐藏菜单栏）
        self.menu = self.menuBar()
        self.manage_packages_action = self.menu.addAction("管理语言包")
        self.manage_packages_action.triggered.connect(
            self.manage_packages_action_triggered
        )
        self.glossary_action = self.menu.addAction("术语库…")
        self.glossary_action.triggered.connect(self.glossary_action_triggered)
        self.history_action = self.menu.addAction("翻译历史…")
        self.history_action.triggered.connect(self.translation_history_action_triggered)
        self.notebook_action = self.menu.addAction("生词本…")
        self.notebook_action.triggered.connect(self.word_notebook_action_triggered)
        self.install_location_action = self.menu.addAction("安装位置…")
        self.install_location_action.triggered.connect(
            self.install_location_action_triggered
        )
        self.check_update_action = self.menu.addAction("检查更新…")
        self.check_update_action.triggered.connect(self.check_update_action_triggered)
        self.about_action = self.menu.addAction("关于")
        self.about_action.triggered.connect(self.about_action_triggered)
        self.menu.setNativeMenuBar(False)

        self.window_layout = QVBoxLayout()
        self.window_layout.setContentsMargins(16, 14, 16, 18)
        self.window_layout.setSpacing(14)

        if self._portable_root is not None:
            chrome = QFrame()
            chrome.setObjectName("AppChrome")
            ch_l = QHBoxLayout(chrome)
            ch_l.setContentsMargins(16, 10, 16, 10)
            title_box = QVBoxLayout()
            title_main = QLabel(_app_display_name())
            title_main.setObjectName("ChromeTitle")
            title_sub = QLabel("俄语 · 乌克兰语")
            title_sub.setObjectName("ChromeSubtitle")
            self._chrome_title_sub = title_sub
            if _fast_startup_enabled():
                QTimer.singleShot(0, self._fill_chrome_version_subtitle)
            title_box.addWidget(title_main)
            title_box.addWidget(title_sub)
            ch_l.addLayout(title_box)
            ch_l.addStretch()
            self._chrome_pkg_btn = QToolButton()
            self._chrome_pkg_btn.setObjectName("ChromeBtn")
            self._chrome_pkg_btn.setText("语言包")
            self._chrome_pkg_btn.clicked.connect(self.manage_packages_action_triggered)
            self._chrome_gloss_btn = QToolButton()
            self._chrome_gloss_btn.setObjectName("ChromeBtn")
            self._chrome_gloss_btn.setText("术语库")
            self._chrome_gloss_btn.clicked.connect(self.glossary_action_triggered)
            self._chrome_hist_btn = None
            if (self._portable_root / "translation_history.py").is_file():
                self._chrome_hist_btn = QToolButton()
                self._chrome_hist_btn.setObjectName("ChromeBtn")
                self._chrome_hist_btn.setText("翻译历史")
                self._chrome_hist_btn.clicked.connect(
                    self.translation_history_action_triggered
                )
            self._chrome_notebook_btn = None
            if (self._portable_root / "word_notebook_dialog.py").is_file():
                self._chrome_notebook_btn = QToolButton()
                self._chrome_notebook_btn.setObjectName("ChromeBtn")
                self._chrome_notebook_btn.setText("生词本")
                self._chrome_notebook_btn.clicked.connect(
                    self.word_notebook_action_triggered
                )
            self._chrome_update_btn = None
            if (self._portable_root / "update_dialog.py").is_file():
                self._chrome_update_btn = QToolButton()
                self._chrome_update_btn.setObjectName("ChromeBtn")
                self._chrome_update_btn.setText("检查更新")
                self._chrome_update_btn.setToolTip(
                    "从 GitHub 检查并下载安装最新版本"
                )
                self._chrome_update_btn.clicked.connect(
                    self.check_update_action_triggered
                )
            self._chrome_about_btn = QToolButton()
            self._chrome_about_btn.setObjectName("ChromeBtn")
            self._chrome_about_btn.setText("关于")
            self._chrome_about_btn.clicked.connect(self.about_action_triggered)
            self._chrome_dark_btn = QToolButton()
            self._chrome_dark_btn.setObjectName("ChromeBtn")
            self._chrome_dark_btn.setToolTip("切换浅色 / 深色主题")
            self._chrome_dark_btn.clicked.connect(self._toggle_dark_mode)
            ch_l.addWidget(self._chrome_pkg_btn)
            ch_l.addWidget(self._chrome_gloss_btn)
            if self._chrome_hist_btn is not None:
                ch_l.addWidget(self._chrome_hist_btn)
            if self._chrome_notebook_btn is not None:
                ch_l.addWidget(self._chrome_notebook_btn)
            if self._chrome_update_btn is not None:
                ch_l.addWidget(self._chrome_update_btn)
            ch_l.addWidget(self._chrome_about_btn)
            ch_l.addWidget(self._chrome_dark_btn)
            self.window_layout.addWidget(chrome)
            self._chrome_dark_btn.setText("深色")
            QTimer.singleShot(80, self._refresh_chrome_dark_label)
            self.menu.setVisible(False)

        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)
        self._tab_widget.currentChanged.connect(self._on_tab_current_changed)
        corner = QWidget()
        corner_l = QHBoxLayout(corner)
        corner_l.setContentsMargins(0, 0, 4, 0)
        self._btn_new_tab = QPushButton("+ 新标签")
        self._btn_new_tab.setObjectName("ChromeBtn")
        self._btn_new_tab.setToolTip("新建独立翻译页（语言与音频设置互不影响）")
        self._btn_new_tab.clicked.connect(lambda: self._add_translation_tab())
        corner_l.addWidget(self._btn_new_tab)
        self._tab_widget.setCornerWidget(corner, Qt.TopRightCorner)
        self.window_layout.addWidget(self._tab_widget, 1)
        self._setup_tab_keyboard_shortcuts()

        self.central_widget = QWidget()
        self.central_widget.setLayout(self.window_layout)
        self.setCentralWidget(self.central_widget)
        self.setWindowTitle(_app_display_name())

        if self._tab_cls is None:
            QMessageBox.warning(
                self,
                _app_display_name(),
                "未找到 translation_tab_page.py，无法启用多标签。",
            )
        else:
            tabs_data = []
            if isinstance(self._session_restore, dict):
                raw_tabs = self._session_restore.get("tabs")
                if isinstance(raw_tabs, list):
                    tabs_data = [t for t in raw_tabs if isinstance(t, dict)]
            if _fast_startup_enabled() and self._portable_root is not None:
                self._prime_lightweight_languages()
            if tabs_data:
                first = tabs_data[0]
                self._add_translation_tab(session_state=first, switch=True)
                if _fast_startup_enabled() and len(tabs_data) > 1:
                    self._deferred_tab_sessions = tabs_data[1:]
                    self._deferred_active_tab = int(
                        self._session_restore.get("active_tab") or 0
                    )
                    QTimer.singleShot(40, self._restore_deferred_tabs)
                elif len(tabs_data) > 1:
                    for td in tabs_data[1:]:
                        self._add_translation_tab(session_state=td, switch=False)
                    active = int(self._session_restore.get("active_tab") or 0)
                    if 0 <= active < self._tab_widget.count():
                        self._tab_widget.setCurrentIndex(active)
                        self._on_tab_current_changed(active)
            else:
                self._add_translation_tab()
            QTimer.singleShot(0, self._restore_window_geometry)

        if self._portable_root is not None and _fast_startup_enabled():
            QTimer.singleShot(0, self._start_language_load_async)
            QTimer.singleShot(2500, self.maybe_open_glossary_on_startup)
        else:
            self.load_languages()
            QTimer.singleShot(0, self.maybe_open_glossary_on_startup)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.KeyPress and self.isActiveWindow():
            mods = event.modifiers()
            if (mods & Qt.ControlModifier) and event.key() == Qt.Key_Tab:
                if mods & Qt.ShiftModifier:
                    self._switch_tab_relative(-1)
                else:
                    self._switch_tab_relative(1)
                return True
        return super().eventFilter(obj, event)

    def _iter_tabs(self):
        for i in range(self._tab_widget.count()):
            w = self._tab_widget.widget(i)
            if w is not None:
                yield w

    def _setup_tab_keyboard_shortcuts(self) -> None:
        """Ctrl+Tab / Ctrl+Shift+Tab 切换翻译标签（与浏览器类似）。"""
        ctx = Qt.WindowShortcut
        sc_next = QShortcut(QKeySequence("Ctrl+Tab"), self)
        sc_next.setContext(ctx)
        sc_next.activated.connect(lambda: self._switch_tab_relative(1))
        sc_prev = QShortcut(QKeySequence("Ctrl+Shift+Tab"), self)
        sc_prev.setContext(ctx)
        sc_prev.activated.connect(lambda: self._switch_tab_relative(-1))
        self._btn_new_tab.setToolTip(
            "新建独立翻译页（语言与音频设置互不影响）\n"
            "快捷键：Ctrl+Tab 下一标签，Ctrl+Shift+Tab 上一标签"
        )

    def _switch_tab_relative(self, delta: int) -> None:
        n = self._tab_widget.count()
        if n <= 1:
            return
        cur = self._tab_widget.currentIndex()
        if cur < 0:
            cur = 0
        self._tab_widget.setCurrentIndex((cur + int(delta)) % n)

    def _add_translation_tab(
        self,
        speech_prefs=None,
        *,
        session_state: dict | None = None,
        switch: bool = True,
    ) -> None:
        if self._tab_cls is None:
            return
        if session_state is None and speech_prefs is None:
            cur = self._tab_widget.currentWidget()
            if cur is not None and hasattr(cur, "_get_speech_audio_prefs"):
                import copy

                speech_prefs = copy.deepcopy(cur._get_speech_audio_prefs())
        if isinstance(session_state, dict) and session_state.get("speech_prefs"):
            import copy

            speech_prefs = copy.deepcopy(session_state["speech_prefs"])
        self._tab_serial += 1
        tab = self._tab_cls(self, self._tab_serial, speech_prefs=speech_prefs)
        if isinstance(session_state, dict):
            tab.apply_session_state(session_state)
        self._tabs.append(tab)
        idx = self._tab_widget.addTab(tab, tab.default_tab_title())
        if switch:
            self._tab_widget.setCurrentIndex(idx)
        if self.languages:
            tab.apply_language_combos(run_translate=False)
        else:
            tab.refresh_tab_title()
        tab._word_lookup_upgraded = (
            hasattr(tab, "_word_lookup_text_edits_ready")
            and tab._word_lookup_text_edits_ready()
        )

    def _restore_window_geometry(self) -> None:
        if not isinstance(self._session_restore, dict):
            return
        geom = self._session_restore.get("geometry")
        if not geom or not isinstance(geom, str):
            return
        try:
            import base64

            data = QByteArray.fromBase64(geom.encode("ascii"))
            if not data.isEmpty():
                self.restoreGeometry(data)
        except Exception:
            pass

    def _finish_restoring_session(self) -> None:
        for tab in self._iter_tabs():
            if hasattr(tab, "finish_session_restore"):
                tab.finish_session_restore()

    def _save_ui_session(self) -> None:
        if self._portable_root is None or self._ui_session_mod is None:
            return
        import base64

        tabs_out = []
        for tab in self._iter_tabs():
            if hasattr(tab, "to_session_dict"):
                tabs_out.append(tab.to_session_dict())
        if not tabs_out:
            return
        geom_b64 = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        data = {
            "version": self._ui_session_mod.SESSION_VERSION,
            "active_tab": max(0, self._tab_widget.currentIndex()),
            "geometry": geom_b64,
            "tabs": tabs_out,
        }
        try:
            self._ui_session_mod.save_session(self._portable_root, data)
        except OSError as e:
            info(f"ui_session save: {e}")

    def _on_tab_close_requested(self, index: int) -> None:
        if self._tab_widget.count() <= 1:
            QMessageBox.information(self, "标签页", "至少保留一个翻译标签页。")
            return
        tab = self._tab_widget.widget(index)
        if tab is not None:
            tab.shutdown()
            if tab in self._tabs:
                self._tabs.remove(tab)
        self._tab_widget.removeTab(index)
        if tab is not None:
            tab.deleteLater()

    def _on_tab_current_changed(self, index: int) -> None:
        if index < 0:
            return
        for i in range(self._tab_widget.count()):
            w = self._tab_widget.widget(i)
            if w is None:
                continue
            if i == index:
                w.on_tab_activated()
            else:
                w.on_tab_deactivated()
        if _fast_startup_enabled():
            QTimer.singleShot(0, self._maybe_deferred_word_lookup_for_tab)

    def _prime_lightweight_languages(self) -> None:
        root = self._portable_root
        if root is None:
            return
        try:
            langs = _load_languages_lightweight(root)
        except Exception:
            return
        if not langs:
            return
        self.languages = langs
        self._languages_lightweight = True
        for tab in self._iter_tabs():
            tab.apply_language_combos(run_translate=False)

    def _restore_deferred_tabs(self) -> None:
        pending = getattr(self, "_deferred_tab_sessions", None)
        if not pending:
            return
        for td in pending:
            self._add_translation_tab(session_state=td, switch=False)
        self._deferred_tab_sessions = []
        active = int(getattr(self, "_deferred_active_tab", 0) or 0)
        if 0 <= active < self._tab_widget.count():
            self._tab_widget.setCurrentIndex(active)
            self._on_tab_current_changed(active)
        QTimer.singleShot(50, self._finish_restoring_session)

    def _maybe_deferred_word_lookup_for_tab(self) -> None:
        tab = self._tab_widget.currentWidget()
        if tab is None or getattr(tab, "_word_lookup_upgraded", False):
            return
        needs = getattr(tab, "_lang_pair_needs_word_lookup", None)
        if needs is not None and not needs():
            return
        ready = getattr(tab, "_word_lookup_text_edits_ready", None)
        if ready is not None and ready():
            tab._word_lookup_upgraded = True
            return
        upgrade = getattr(tab, "_upgrade_word_lookup_text_edits", None)
        if upgrade is None:
            upgrade = getattr(tab, "_upgrade_right_text_edit_word_info", None)
        if upgrade is not None:
            QTimer.singleShot(0, upgrade)
        tab._word_lookup_upgraded = True

    def _pause_other_tabs_speech(self, active_tab) -> None:
        for tab in self._iter_tabs():
            if tab is active_tab:
                continue
            tab.on_tab_deactivated()
            w = getattr(tab, "_offline_speech_worker", None)
            if w is not None and w.isRunning() and w.is_recording_allowed():
                w.pause_recording()

    def _fill_chrome_version_subtitle(self) -> None:
        sub = getattr(self, "_chrome_title_sub", None)
        if sub is None or self._portable_root is None:
            return
        ver_mod = _import_app_version_module()
        if ver_mod is None:
            return
        ver = ver_mod.format_version_label(self._portable_root)
        if ver:
            sub.setText(f"俄语 · 乌克兰语 · {ver}")

    def _refresh_chrome_dark_label(self) -> None:
        if self._portable_root is None:
            return
        theme = self._portable_root / "portable_ui_theme.py"
        if not theme.is_file():
            return
        try:
            spec = importlib.util.spec_from_file_location("portable_ui_theme", theme)
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            dark = mod.load_dark_mode(self._portable_root)
            self._chrome_dark_btn.setText("浅色" if dark else "深色")
        except Exception:
            self._chrome_dark_btn.setText("深色")

    def _toggle_dark_mode(self) -> None:
        root = self._portable_root
        if root is None:
            return
        theme = root / "portable_ui_theme.py"
        if not theme.is_file():
            return
        try:
            spec = importlib.util.spec_from_file_location("portable_ui_theme", theme)
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.toggle_dark_mode(QApplication.instance(), root)
            self._refresh_chrome_dark_label()
        except Exception as e:
            info(f"toggle_dark_mode: {e}")

    def translation_history_action_triggered(self) -> None:
        mod = _import_translation_history_module()
        if mod is None:
            QMessageBox.warning(
                self,
                "翻译历史",
                "未找到便携版根目录下的 translation_history.py，无法读写历史。",
            )
            return
        items = mod.load_items()
        dlg = TranslationHistoryDialog(self, items)
        dlg.exec_()

    def word_notebook_action_triggered(self) -> None:
        mod = _import_word_notebook_module()
        if mod is None:
            QMessageBox.warning(
                self,
                "生词本",
                "未找到便携版根目录下的 word_notebook_dialog.py。",
            )
            return
        if getattr(self, "_word_notebook_dialog", None) is not None:
            d = self._word_notebook_dialog
            d.show()
            d.raise_()
            d.activateWindow()
            if hasattr(d, "reload_table"):
                d.reload_table()
            return
        dlg = mod.WordNotebookDialog(self, self)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.Window)
        self._word_notebook_dialog = dlg
        dlg.show()

    def maybe_open_glossary_on_startup(self):
        mod = _import_glossary_editor_module()
        if mod is None:
            return
        if mod.load_open_on_startup():
            self.open_glossary_editor()

    def install_location_action_triggered(self):
        try:
            import install_location_dialog as ild
        except ImportError:
            QMessageBox.warning(self, "安装位置", "未找到 install_location_dialog.py。")
            return
        ild.open_install_location_dialog(self)

    def check_update_action_triggered(self):
        try:
            import update_dialog as ud
        except ImportError:
            QMessageBox.warning(self, "检查更新", "未找到 update_dialog.py。")
            return
        ud.open_update_dialog(self)

    def open_glossary_editor(self):
        mod = _import_glossary_editor_module()
        if mod is None:
            QMessageBox.warning(self, "术语库", "未找到 glossary_editor.py。")
            return
        if getattr(self, "_glossary_editor_dialog", None) is not None:
            d = self._glossary_editor_dialog
            d.show()
            d.raise_()
            d.activateWindow()
            return
        dlg = mod.GlossaryEditorDialog(self)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.Window)
        self._glossary_editor_dialog = dlg
        dlg.show()

    def swap_languages_button_clicked(self):
        self._pulse_swap_button()
        left_index = self.left_language_combo.currentIndex()
        self.left_language_combo.setCurrentIndex(
            self.right_language_combo.currentIndex()
        )
        self.right_language_combo.setCurrentIndex(left_index)

    def about_action_triggered(self):
        about_message_box = QMessageBox()
        about_message_box.setWindowTitle("关于")
        base = getattr(settings, "about_text", settings.argos_translate_about_text)
        extra = ""
        ver_mod = _import_app_version_module()
        if ver_mod is not None and self._portable_root is not None:
            data = ver_mod.read_version_json(self._portable_root)
            ver = data.get("version") or ver_mod.APP_VERSION
            extra = (
                f"\n\n{ver_mod.APP_NAME} 便携版 {ver}\n"
                f"安装目录：{self._portable_root}\n\n"
                f"更新方式：下载新版「{ver_mod.APP_NAME}-x.y.z-更新.exe」，双击运行；"
                "程序会自动覆盖程序文件并保留 data（语言包、术语库、语音模型等），"
                "完成后启动翻译界面。首次会提示选择安装文件夹，之后会记住路径。"
            )
        about_message_box.setText(base + extra)
        about_message_box.setIcon(QMessageBox.Information)
        about_message_box.exec_()

    def glossary_action_triggered(self):
        self.open_glossary_editor()

    def manage_packages_action_triggered(self):
        self.packages_window = ManagePackagesWindow()
        self.packages_window.packages_changed.connect(self.load_languages)
        self.packages_window.show()

    def _start_language_load_async(self) -> None:
        if not self.languages:
            for tab in self._iter_tabs():
                tab.right_textEdit.setPlaceholderText("正在加载语言包…")
                tab.left_language_combo.setEnabled(False)
                tab.right_language_combo.setEnabled(False)
        self._lang_load_worker = LanguageLoadWorker()
        self._lang_load_worker.finished_ok.connect(self._on_languages_loaded)
        self._lang_load_worker.failed.connect(self._on_languages_load_failed)
        self._lang_load_worker.start()

    def _on_languages_load_failed(self, msg: str) -> None:
        self._lang_load_worker = None
        root = self._portable_root
        if root is not None:
            try:
                langs = _load_languages_lightweight(root)
                if langs:
                    self._apply_loaded_languages(langs, lightweight=True, full_error=msg)
                    return
            except Exception:
                pass
        for tab in self._iter_tabs():
            tab.left_language_combo.setEnabled(True)
            tab.right_language_combo.setEnabled(True)
            tab.right_textEdit.setPlaceholderText("语言包加载失败，请检查 data\\local 下的模型。")
        if _is_torch_dll_init_error(msg):
            self._handle_torch_engine_failure(msg)
        else:
            QMessageBox.warning(self, _app_display_name(), f"加载语言包失败：\n{msg}")

    def _show_engine_restart_required(self, error_text: str = "") -> None:
        """运行库已装或已执行过安装：提示重启，不再重复下载。"""
        text = (
            "翻译引擎在当前窗口中仍无法加载。\n\n"
            "若刚安装过 Visual C++ 运行库，必须完全退出本程序"
            "（任务管理器中结束所有 pythonw.exe），再重新运行 run_gui.bat。\n\n"
            "同一窗口内反复「重试」通常无效，请勿重复下载安装。\n\n"
            "若重启后仍失败：在显卡设置中将本目录下的 pythonw.exe 设为「高性能」独显。"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(_app_display_name())
        box.setText(text)
        if error_text:
            short = error_text if len(error_text) < 1200 else error_text[:1200] + "…"
            box.setDetailedText(short)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec_()

    def _handle_torch_engine_failure(self, error_text: str, *, from_retry: bool = False) -> None:
        if self._vcredist_install_done or _vcredist_already_handled() or from_retry:
            self._show_engine_restart_required(error_text)
            return
        self._maybe_offer_vcredist_install(error_text)

    def _maybe_offer_vcredist_install(self, error_text: str = "") -> None:
        if sys.platform != "win32" or self._portable_root is None:
            return
        if error_text and not _is_torch_dll_init_error(error_text):
            return
        if self._vcredist_install_done or _vcredist_already_handled():
            self._show_engine_restart_required(error_text)
            return
        if _import_vcredist_helper() is None:
            QMessageBox.warning(
                self,
                _app_display_name(),
                "翻译引擎加载失败，需要安装 Microsoft Visual C++ 2015-2022（x64）运行库。",
            )
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(_app_display_name())
        box.setText(
            "翻译引擎需要 Microsoft Visual C++ 2015-2022 运行库（x64）。\n\n"
            "是否现在从 Microsoft 官方服务器下载并安装？\n"
            "（可能出现 Windows 管理员 UAC 提示，请选择「是」。）"
        )
        if error_text:
            short = error_text if len(error_text) < 1200 else error_text[:1200] + "…"
            box.setDetailedText(short)
        btn_go = box.addButton("立即下载并安装", QMessageBox.AcceptRole)
        box.addButton("稍后", QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() != btn_go:
            return
        self._start_vcredist_install()

    def _start_vcredist_install(self) -> None:
        root = self._portable_root
        if root is None or self._vcredist_worker is not None:
            return
        self._vcredist_progress = QProgressDialog(
            "准备下载…", None, 0, 0, self
        )
        self._vcredist_progress.setWindowTitle("安装 Visual C++ 运行库")
        self._vcredist_progress.setMinimumDuration(0)
        self._vcredist_progress.setCancelButton(None)
        self._vcredist_progress.setWindowModality(Qt.WindowModal)
        self._vcredist_progress.show()
        self._vcredist_worker = VcredistInstallWorker(root, self)
        self._vcredist_worker.status.connect(self._on_vcredist_install_status)
        self._vcredist_worker.finished_result.connect(self._on_vcredist_install_finished)
        self._vcredist_worker.finished.connect(self._clear_vcredist_worker)
        self._vcredist_worker.start()

    def _on_vcredist_install_status(self, text: str) -> None:
        if self._vcredist_progress is not None:
            self._vcredist_progress.setLabelText(text)

    def _clear_vcredist_worker(self) -> None:
        self._vcredist_worker = None

    def _on_vcredist_install_finished(self, ok: bool, msg: str) -> None:
        if self._vcredist_progress is not None:
            self._vcredist_progress.close()
            self._vcredist_progress = None
        if ok:
            self._vcredist_install_done = True
            QMessageBox.information(
                self,
                _app_display_name(),
                msg
                + "\n\n请完全退出本程序后重新运行 run_gui.bat（任务管理器结束 pythonw.exe）。"
                + "\n安装后不要在本窗口内重试，必须新开进程才能加载翻译引擎。",
            )
        else:
            QMessageBox.warning(self, _app_display_name(), f"运行库安装未完成：\n{msg}")

    def _retry_load_translation_engine(self) -> None:
        """同进程内重试（多数情况下需重启程序才有效）。"""
        if self._portable_root is not None:
            _prepare_native_dll(self._portable_root)
        _reset_translation_engine_modules()
        try:
            langs = _get_argos_translate().get_installed_languages()
        except Exception as e:
            if _is_torch_dll_init_error(str(e)):
                self._handle_torch_engine_failure(str(e), from_retry=True)
            else:
                QMessageBox.warning(self, _app_display_name(), f"仍无法加载翻译引擎：\n{e}")
            return
        if langs:
            self._apply_loaded_languages(langs, lightweight=False)
            QMessageBox.information(self, _app_display_name(), "翻译引擎已就绪，可以开始翻译。")

    def _apply_loaded_languages(
        self,
        languages: object,
        *,
        lightweight: bool = False,
        full_error: str = "",
    ) -> None:
        self.languages = list(languages) if languages else []
        self._languages_lightweight = lightweight
        self._lang_load_full_error = full_error if lightweight else ""
        placeholder = "译文将显示在此处。"
        if lightweight:
            placeholder = (
                "已读取本地语言列表；翻译引擎未就绪时请点击顶栏提示安装运行库。"
            )
        for tab in self._iter_tabs():
            tab.left_language_combo.setEnabled(True)
            tab.right_language_combo.setEnabled(True)
            if lightweight:
                tab.right_textEdit.setPlaceholderText(placeholder)
            else:
                tab.right_textEdit.setPlaceholderText(placeholder)
            tab.apply_language_combos(run_translate=False)
        QTimer.singleShot(150, self._finish_restoring_session)
        if lightweight and full_error and _is_torch_dll_init_error(full_error):
            QTimer.singleShot(
                300, lambda: self._handle_torch_engine_failure(full_error)
            )

    def _on_languages_loaded(self, languages: object, lightweight: bool = False) -> None:
        full_err = ""
        w = self._lang_load_worker
        if w is not None:
            full_err = getattr(w, "_last_full_error", "") or ""
        self._lang_load_worker = None
        self._apply_loaded_languages(
            languages, lightweight=lightweight, full_error=full_err
        )

    def try_reload_full_languages(self) -> bool:
        """轻量语言列表模式下，翻译前再尝试完整加载（含翻译路由）。"""
        root = self._portable_root
        if root is not None and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        if not self._languages_lightweight:
            return bool(self.languages)
        root = self._portable_root
        if root is not None:
            _prepare_native_dll(root)
        try:
            langs = _get_argos_translate().get_installed_languages()
        except Exception as e:
            if _is_torch_dll_init_error(str(e)):
                self._handle_torch_engine_failure(str(e), from_retry=True)
            return False
        if not langs:
            return False
        saved: list[tuple[str, str]] = []
        for tab in self._iter_tabs():
            li = tab.left_language_combo.currentIndex()
            ri = tab.right_language_combo.currentIndex()
            src = (self.languages[li].code if 0 <= li < len(self.languages) else "")
            tgt = (self.languages[ri].code if 0 <= ri < len(self.languages) else "")
            saved.append((src, tgt))
        self._apply_loaded_languages(langs, lightweight=False)
        for tab, (src, tgt) in zip(self._iter_tabs(), saved):
            if src or tgt:
                tab.apply_language_codes(src, tgt)
        return True

    def load_languages(self):
        root = self._portable_root
        if root is not None:
            _prepare_native_dll(root)
        try:
            self.languages = _get_argos_translate().load_installed_languages()
            self._languages_lightweight = False
            self._lang_load_full_error = ""
        except Exception as e:
            err = _dll_load_hint(str(e))
            if root is not None:
                langs = _load_languages_lightweight(root)
                if langs:
                    self._apply_loaded_languages(langs, lightweight=True, full_error=err)
                    return
            if _is_torch_dll_init_error(err):
                self._handle_torch_engine_failure(err)
            else:
                QMessageBox.warning(self, _app_display_name(), f"加载语言包失败：\n{err}")
            return
        for tab in self._iter_tabs():
            tab.apply_language_combos(run_translate=not _fast_startup_enabled())
        if self._session_restore:
            QTimer.singleShot(150, self._finish_restoring_session)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._save_ui_session()
        for tab in self._iter_tabs():
            tab.shutdown()
        super().closeEvent(event)


class GUIApplication:
    def __init__(self):
        _set_windows_app_user_model_id()
        self.app = QApplication([])
        self.app.setApplicationName(_app_display_name())
        # Qt 标准控件（文件对话框等）使用简体中文
        qt_translator = QTranslator()
        translations_path = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
        if qt_translator.load(QLocale(QLocale.Chinese, QLocale.China), "qtbase", "_", translations_path):
            self.app.installTranslator(qt_translator)
        qt_translator2 = QTranslator()
        if qt_translator2.load(QLocale(QLocale.Chinese, QLocale.China), "qt", "_", translations_path):
            self.app.installTranslator(qt_translator2)
        if _fast_startup_enabled() and _portable_bundle_root() is not None:
            _try_apply_portable_ui_theme(self.app)
        self.main_window = GUIWindow()
        self._apply_window_icon()
        self.main_window.show()
        self.app.processEvents()
        if not _fast_startup_enabled():
            _try_apply_portable_ui_theme(self.app)
        QTimer.singleShot(
            0, lambda: _apply_windows_taskbar_icon(self.main_window)
        )
        self.app.exec_()

    def _apply_window_icon(self) -> None:
        icon = QIcon()
        pip = _portable_app_icon_path()
        if pip is not None:
            icon = QIcon(str(pip))
        else:
            icon_path = Path(os.path.dirname(__file__)) / "img" / "icon.png"
            if icon_path.is_file():
                icon = QIcon(str(icon_path))
        if not icon.isNull():
            self.app.setWindowIcon(icon)
            self.main_window.setWindowIcon(icon)


def main():
    import logging

    _set_windows_app_user_model_id()
    logging.getLogger("argostranslate").setLevel(logging.WARNING)
    logging.getLogger("ctranslate2").setLevel(logging.WARNING)
    logging.getLogger("stanza").setLevel(logging.WARNING)
    app = GUIApplication()
