"""
ArgosTranslate 便携版 UI 主题（QSS + Fusion）。
浅色：科技蓝主色 #1A73E8、浅灰背景 #F8F9FA（对齐方案文档）。
深色：独立色板，可菜单/顶栏切换。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# —— 浅色（Material / Google 系）——
PALETTE_LIGHT: dict[str, str] = {
    "bg": "#F8F9FA",
    "surface": "#FFFFFF",
    "surface_alt": "#F1F3F4",
    "border": "#DADCE0",
    "border_strong": "#BDC1C6",
    "text": "#3C4043",
    "text_muted": "#70757A",
    "accent": "#1A73E8",
    "accent_hover": "#1558B0",
    "accent_pressed": "#0D47A1",
    "success": "#34A853",
    "success_hover": "#2E7D32",
    "teal": "#1A73E8",
    "teal_hover": "#1558B0",
    "danger": "#D93025",
    "danger_hover": "#B31412",
    "menu_bg": "#E8F0FE",
    "scroll": "#BDC1C6",
    "scroll_hover": "#9AA0A6",
    "placeholder": "#9AA0A6",
    "focus": "#1A73E8",
    "sel_bg": "#D2E3FC",
    "sel_fg": "#202124",
    "chrome_bg": "#1A73E8",
    "chrome_fg": "#FFFFFF",
    "chrome_sub": "rgba(255,255,255,0.85)",
    "badge_bg": "#E8F0FE",
    "badge_bd": "#AECBFA",
    "tab_muted": "#5F6368",
}

# —— 深色 ——
PALETTE_DARK: dict[str, str] = {
    "bg": "#202124",
    "surface": "#303134",
    "surface_alt": "#3C4043",
    "border": "#5F6368",
    "border_strong": "#80868B",
    "text": "#E8EAED",
    "text_muted": "#9AA0A6",
    "accent": "#8AB4F8",
    "accent_hover": "#AECBFA",
    "accent_pressed": "#669DF6",
    "success": "#81C995",
    "success_hover": "#A8DAB5",
    "teal": "#8AB4F8",
    "teal_hover": "#AECBFA",
    "danger": "#F28B82",
    "danger_hover": "#EE675C",
    "menu_bg": "#303134",
    "scroll": "#5F6368",
    "scroll_hover": "#80868B",
    "placeholder": "#80868B",
    "focus": "#8AB4F8",
    "sel_bg": "#174EA6",
    "sel_fg": "#E8EAED",
    "chrome_bg": "#174EA6",
    "chrome_fg": "#E8EAED",
    "chrome_sub": "rgba(232,234,237,0.8)",
    "badge_bg": "#3C4043",
    "badge_bd": "#5F6368",
    "tab_muted": "#9AA0A6",
}


def ui_prefs_path(portable_root: Path) -> Path:
    return portable_root / "data" / "config" / "ui_prefs.json"


def load_dark_mode(portable_root: Path) -> bool:
    p = ui_prefs_path(portable_root)
    if not p.is_file():
        return False
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return bool(d.get("dark_mode", False))
    except (json.JSONDecodeError, OSError):
        return False


def save_dark_mode(portable_root: Path, dark: bool) -> None:
    p = ui_prefs_path(portable_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    other: dict[str, Any] = {}
    if p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                other = json.load(f)
            if not isinstance(other, dict):
                other = {}
        except (json.JSONDecodeError, OSError):
            other = {}
    other["dark_mode"] = dark
    with open(p, "w", encoding="utf-8") as f:
        json.dump(other, f, ensure_ascii=False, indent=2)


def build_application_stylesheet(dark: bool = False) -> str:
    x = PALETTE_DARK if dark else PALETTE_LIGHT
    return f"""
    QDialog {{
        background-color: {x["bg"]};
    }}
    QWidget {{
        background-color: {x["bg"]};
        color: {x["text"]};
        font-size: 13px;
        font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC", Roboto, sans-serif;
    }}
    QMainWindow {{
        background-color: {x["bg"]};
    }}
    QFrame#AppChrome {{
        background-color: {x["chrome_bg"]};
        border: none;
        border-radius: 0px;
        min-height: 52px;
    }}
    QLabel#ChromeTitle {{
        color: {x["chrome_fg"]};
        font-size: 18px;
        font-weight: 700;
        background: transparent;
    }}
    QLabel#ChromeSubtitle {{
        color: {x["chrome_sub"]};
        font-size: 12px;
        background: transparent;
    }}
    QToolButton#ChromeBtn {{
        background-color: rgba(255,255,255,0.12);
        color: {x["chrome_fg"]};
        border: 1px solid rgba(255,255,255,0.35);
        border-radius: 8px;
        padding: 8px 14px;
        font-weight: 600;
        margin-left: 4px;
    }}
    QToolButton#ChromeBtn:hover {{
        background-color: rgba(255,255,255,0.22);
        border-color: rgba(255,255,255,0.55);
    }}
    QToolButton#ChromeBtn:pressed {{
        background-color: rgba(0,0,0,0.15);
    }}
    QFrame#LangBar {{
        background-color: {x["surface"]};
        border: 1px solid {x["border"]};
        border-radius: 12px;
    }}
    QWidget#SpeechSettingsPanel {{
        background-color: {x["surface_alt"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
    }}
    QLabel#CharCount {{
        color: {x["text_muted"]};
        font-size: 12px;
        background: transparent;
    }}
    QPushButton#TextAction {{
        background-color: {x["surface_alt"]};
        color: {x["text_muted"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
        padding: 4px 12px;
        font-size: 12px;
        min-height: 18px;
    }}
    QPushButton#TextAction:hover {{
        background-color: {x["surface"]};
        color: {x["accent"]};
        border-color: {x["accent"]};
    }}
    QMenuBar {{
        background-color: {x["menu_bg"]};
        color: {x["text"]};
        border-bottom: 1px solid {x["border"]};
        padding: 4px 8px;
        spacing: 6px;
    }}
    QMenuBar::item {{
        padding: 6px 12px;
        border-radius: 6px;
        background: transparent;
    }}
    QMenuBar::item:selected {{
        background-color: {x["surface_alt"]};
        color: {x["accent"]};
    }}
    QMenu {{
        background-color: {x["surface"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 8px 28px 8px 14px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background-color: {x["surface_alt"]};
        color: {x["accent"]};
    }}
    QToolTip {{
        background-color: {x["text"]};
        color: {x["surface"]};
        border: none;
        border-radius: 6px;
        padding: 6px 10px;
    }}
    QMessageBox {{
        background-color: {x["surface"]};
    }}
    QMessageBox QLabel {{
        color: {x["text"]};
        min-width: 280px;
    }}
    QPushButton {{
        background-color: {x["surface"]};
        color: {x["text"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
        padding: 8px 16px;
        min-height: 20px;
    }}
    QPushButton:hover {{
        background-color: {x["surface_alt"]};
        border-color: {x["border_strong"]};
    }}
    QPushButton:pressed {{
        background-color: {x["border"]};
    }}
    QPushButton:disabled {{
        color: {x["placeholder"]};
        background-color: {x["surface_alt"]};
    }}
    QPushButton#AccentButton {{
        background-color: {x["accent"]};
        color: #ffffff;
        border: none;
        font-weight: 600;
    }}
    QPushButton#AccentButton:hover {{
        background-color: {x["accent_hover"]};
    }}
    QPushButton#AccentButton:pressed {{
        background-color: {x["accent_pressed"]};
    }}
    QPushButton#PrimaryButton {{
        background-color: {x["success"]};
        color: #ffffff;
        border: none;
        font-weight: 600;
        min-width: 96px;
    }}
    QPushButton#PrimaryButton:hover {{
        background-color: {x["success_hover"]};
    }}
    QPushButton#DangerButton {{
        background-color: {x["surface"]};
        color: {x["danger"]};
        border: 1px solid {x["danger"]};
    }}
    QPushButton#DangerButton:hover {{
        background-color: {x["surface_alt"]};
        border-color: {x["danger_hover"]};
    }}
    QPushButton#GhostButton {{
        background-color: transparent;
        border: 1px solid {x["border"]};
        color: {x["text_muted"]};
    }}
    QPushButton#GhostButton:hover {{
        background-color: {x["surface_alt"]};
        color: {x["text"]};
    }}
    QPushButton#SwapButton {{
        background-color: {x["surface"]};
        border: 2px solid {x["accent"]};
        border-radius: 22px;
        min-width: 44px;
        max-width: 44px;
        min-height: 44px;
        max-height: 44px;
        padding: 0px;
        font-size: 18px;
        font-weight: bold;
        color: {x["accent"]};
    }}
    QPushButton#SwapButton:hover {{
        background-color: {x["surface_alt"]};
        border-color: {x["accent_hover"]};
        color: {x["accent_hover"]};
    }}
    QPushButton#SwapButton:pressed {{
        background-color: {x["sel_bg"]};
    }}
    QComboBox {{
        background-color: {x["surface"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
        padding: 10px 14px;
        min-height: 24px;
        min-width: 140px;
        font-weight: 500;
    }}
    QComboBox:hover {{
        border-color: {x["accent"]};
    }}
    QComboBox:focus {{
        border-color: {x["focus"]};
        border-width: 2px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 32px;
    }}
    QComboBox::down-arrow {{
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {x["text_muted"]};
        margin-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background: {x["surface"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
        selection-background-color: {x["sel_bg"]};
        selection-color: {x["accent"]};
        padding: 4px;
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: {x["surface"]};
        color: {x["text"]};
        border: 1px solid {x["border"]};
        border-radius: 12px;
        padding: 14px;
        selection-background-color: {x["sel_bg"]};
        selection-color: {x["sel_fg"]};
        font-size: 14px;
        line-height: 1.45;
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {x["focus"]};
        border-width: 2px;
    }}
    QLineEdit {{
        background-color: {x["surface"]};
        border: 1px solid {x["border"]};
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 18px;
    }}
    QLineEdit:focus {{
        border-color: {x["focus"]};
    }}
    QGroupBox {{
        font-weight: 600;
        color: {x["text"]};
        border: 1px solid {x["border"]};
        border-radius: 10px;
        margin-top: 20px;
        padding-top: 14px;
        background-color: {x["surface"]};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 2px 8px;
        background-color: {x["surface"]};
        color: {x["accent"]};
    }}
    QTabWidget::pane {{
        border: 1px solid {x["border"]};
        border-radius: 10px;
        padding: 10px;
        margin-top: 6px;
        background-color: {x["surface"]};
    }}
    QTabBar::tab {{
        background-color: {x["surface_alt"]};
        color: {x["tab_muted"]};
        border: 1px solid {x["border"]};
        padding: 10px 20px;
        margin-right: 4px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        min-width: 72px;
    }}
    QTabBar::tab:selected {{
        background-color: {x["surface"]};
        color: {x["text"]};
        font-weight: 600;
        border-bottom-color: {x["surface"]};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {x["surface"]};
        color: {x["text"]};
    }}
    QTableWidget {{
        background-color: {x["surface"]};
        alternate-background-color: {x["surface_alt"]};
        border: 1px solid {x["border"]};
        border-radius: 10px;
        gridline-color: {x["border"]};
        selection-background-color: {x["sel_bg"]};
        selection-color: {x["text"]};
    }}
    QTableWidget::item {{
        padding: 6px;
    }}
    QHeaderView::section {{
        background-color: {x["surface_alt"]};
        color: {x["text_muted"]};
        padding: 10px 8px;
        border: none;
        border-bottom: 2px solid {x["border"]};
        border-right: 1px solid {x["border"]};
        font-weight: 600;
    }}
    QHeaderView::section:first {{
        border-top-left-radius: 8px;
    }}
    QCheckBox {{
        spacing: 8px;
        color: {x["text"]};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid {x["border_strong"]};
        background: {x["surface"]};
    }}
    QCheckBox::indicator:checked {{
        background-color: {x["accent"]};
        border-color: {x["accent"]};
    }}
    QScrollBar:vertical {{
        background: {x["surface_alt"]};
        width: 10px;
        margin: 4px 2px 4px 0;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical {{
        background: {x["scroll"]};
        min-height: 32px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {x["scroll_hover"]};
    }}
    QScrollBar:horizontal {{
        background: {x["surface_alt"]};
        height: 10px;
        margin: 0 2px 4px 2px;
        border-radius: 5px;
    }}
    QScrollBar::handle:horizontal {{
        background: {x["scroll"]};
        min-width: 32px;
        border-radius: 5px;
    }}
    QLabel#HintLabel {{
        color: {x["text_muted"]};
        font-size: 12px;
        line-height: 1.45;
        padding: 10px 12px;
        background-color: {x["surface_alt"]};
        border: 1px solid {x["border"]};
        border-radius: 10px;
    }}
    QLabel#BadgeLabel {{
        color: {x["accent"]};
        font-weight: 600;
        font-size: 12px;
        padding: 4px 10px;
        background-color: {x["badge_bg"]};
        border-radius: 6px;
        border: 1px solid {x["badge_bd"]};
    }}
    QLabel#RowCountLabel {{
        color: {x["text_muted"]};
        font-size: 12px;
        padding: 4px 10px;
    }}
    QLabel#MetaLabel {{
        color: {x["text_muted"]};
        font-size: 14px;
        line-height: 1.45;
        padding: 6px 4px;
    }}
    QWidget#WordLookupSlot {{
        background: transparent;
    }}
    QWidget#WordLookupPanel {{
        background-color: {x["surface_alt"]};
        border: 1px solid {x["border"]};
        border-radius: 10px;
        min-width: 260px;
    }}
    QSplitter#TranslationSplitter::handle {{
        background: {x["border"]};
        width: 10px;
        margin: 2px 0;
        border-radius: 4px;
    }}
    QSplitter#TranslationSplitter::handle:hover {{
        background: {x["accent"]};
    }}
    QLabel#WordLookupHead {{
        color: {x["text"]};
        font-weight: 600;
        font-size: 16px;
        line-height: 1.35;
        padding: 4px 4px 8px 4px;
    }}
    QTextBrowser#WordLookupBrowser {{
        font-size: 16px;
        line-height: 1.55;
        min-height: 240px;
        selection-background-color: {x["sel_bg"]};
        selection-color: {x["sel_fg"]};
    }}
    QTextBrowser {{
        background-color: {x["surface"]};
        border: 1px solid {x["border"]};
        border-radius: 10px;
        padding: 10px;
        selection-background-color: {x["sel_bg"]};
        selection-color: {x["sel_fg"]};
    }}
    """


def apply_application_theme(app, *, portable_root: Path | None = None, dark: bool | None = None) -> None:
    from PyQt5.QtWidgets import QStyleFactory

    if dark is None:
        if portable_root is not None:
            dark = load_dark_mode(portable_root)
        else:
            dark = False
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setStyleSheet(build_application_stylesheet(dark=dark))


def toggle_dark_mode(app, portable_root: Path) -> bool:
    """切换深色并保存偏好；返回当前是否为深色。"""
    newv = not load_dark_mode(portable_root)
    save_dark_mode(portable_root, newv)
    apply_application_theme(app, portable_root=portable_root, dark=newv)
    return newv


def polish_widget(w) -> None:
    st = w.style()
    st.unpolish(w)
    st.polish(w)


def apply_glossary_button_roles(
    btn_save,
    btn_add_one,
    btn_bulk,
    btn_close,
    btn_clear_all,
    btn_del,
) -> None:
    """术语库窗口主要按钮语义色。"""
    btn_save.setObjectName("PrimaryButton")
    btn_add_one.setObjectName("AccentButton")
    btn_bulk.setObjectName("AccentButton")
    btn_close.setObjectName("GhostButton")
    btn_clear_all.setObjectName("DangerButton")
    btn_del.setObjectName("DangerButton")
    for b in (
        btn_save,
        btn_add_one,
        btn_bulk,
        btn_close,
        btn_clear_all,
        btn_del,
    ):
        polish_widget(b)
