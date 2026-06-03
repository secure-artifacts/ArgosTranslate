"""TM 导入、导出等操作（供 TM 查看页调用）。"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox


def export_tm(
    parent,
    source_lang: str = "",
    target_lang: str = "",
    *,
    on_message: Callable[[str], None] | None = None,
) -> bool:
    sl_in = (source_lang or "").strip()
    tl_in = (target_lang or "").strip()
    has_pair = bool(sl_in and tl_in)
    if has_pair:
        scope = QMessageBox.question(
            parent,
            "导出 TM",
            f"选择导出范围：\n"
            f"· 是 = 仅 {sl_in} → {tl_in}\n"
            "· 否 = 全部 TM 条目\n"
            "· 取消 = 放弃",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
    else:
        scope = QMessageBox.question(
            parent,
            "导出 TM",
            "选择导出范围：\n"
            "· 是 = 仅当前语言对\n"
            "· 否 = 全部 TM 条目\n"
            "· 取消 = 放弃",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
    if scope == QMessageBox.Cancel:
        return False
    sl, tl = ("", "")
    default_name = "tm_all.json"
    if scope == QMessageBox.Yes and has_pair:
        sl, tl = sl_in, tl_in
        default_name = f"tm_{sl}_{tl}.json"
    try:
        from portable_paths import find_portable_root

        root = find_portable_root()
    except ImportError:
        root = Path.cwd()
    path, _ = QFileDialog.getSaveFileName(
        parent,
        "导出 TM（本地文件）",
        str(root / default_name),
        "JSON (*.json);;JSONL (*.jsonl);;CSV (*.csv);;所有文件 (*.*)",
    )
    if not path:
        return False
    try:
        import translation_memory as tm

        result = tm.export_to_file(
            path,
            source_lang=sl or None,
            target_lang=tl or None,
        )
    except Exception as e:
        QMessageBox.warning(parent, "导出 TM", str(e))
        return False
    n = result.get("count", 0)
    if on_message:
        on_message(f"已导出 TM {n} 条")
    QMessageBox.information(
        parent,
        "导出 TM",
        f"已写入本地文件（共 {n} 条）：\n{path}\n\n数据不会上传网络。",
    )
    return True


def import_tm_file(
    parent,
    source_lang: str = "",
    target_lang: str = "",
    *,
    on_message: Callable[[str], None] | None = None,
    on_success: Callable[[], None] | None = None,
) -> bool:
    try:
        from portable_paths import find_portable_root

        root = find_portable_root()
    except ImportError:
        root = Path.cwd()
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "导入 TM",
        str(root),
        "TM 文件 (*.json *.jsonl *.csv);;所有文件 (*.*)",
    )
    if not path:
        return False
    sl, tl = (source_lang or "").strip(), (target_lang or "").strip()
    r = QMessageBox.question(
        parent,
        "导入 TM",
        "将合并导入句对到本地 TM（重复源句会跳过）。\n"
        f"CSV 若无语言列，将使用：{sl or '?'} → {tl or '?'}\n\n"
        "是否继续？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if r != QMessageBox.Yes:
        return False
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        import translation_memory as tm

        result = tm.import_from_file(
            path,
            source_lang=sl,
            target_lang=tl,
            quality_gate=False,
            bidirectional=True,
        )
    except Exception as e:
        QMessageBox.warning(parent, "导入 TM", str(e))
        return False
    finally:
        QApplication.restoreOverrideCursor()
    if not result.get("ok"):
        QMessageBox.warning(
            parent,
            "导入 TM",
            result.get("reason") or "导入失败",
        )
        return False
    added = result.get("added", 0)
    skipped = result.get("skipped", 0)
    total = result.get("total_in_db", 0)
    if on_message:
        on_message(f"TM +{added}（库内 {total}）")
    QMessageBox.information(
        parent,
        "导入 TM",
        f"解析 {result.get('parsed', 0)} 条\n"
        f"新增 {added} 条，跳过 {skipped} 条\n"
        + (
            f"批量去重 {result.get('dup_skipped', 0)} 条\n"
            if result.get("dup_skipped")
            else ""
        )
        + f"当前 TM 总计 {total} 条",
    )
    if on_success:
        on_success()
    return True


def batch_import_tm_files(
    parent,
    source_lang: str = "",
    target_lang: str = "",
    *,
    on_message: Callable[[str], None] | None = None,
    on_success: Callable[[], None] | None = None,
) -> bool:
    try:
        from portable_paths import find_portable_root

        root = find_portable_root()
    except ImportError:
        root = Path.cwd()
    files, _ = QFileDialog.getOpenFileNames(
        parent,
        "批量导入 TM（可多选文件）",
        str(root),
        "TM 文件 (*.json *.jsonl *.csv);;所有文件 (*.*)",
    )
    folder = ""
    if not files:
        folder = QFileDialog.getExistingDirectory(
            parent,
            "或选择包含 TM 文件的文件夹",
            str(root),
        )
        if not folder:
            return False
        paths = [folder]
    else:
        paths = list(files)
    sl, tl = (source_lang or "").strip(), (target_lang or "").strip()
    n_files = len(paths) if folder else len(files)
    r = QMessageBox.question(
        parent,
        "批量导入 TM",
        f"将合并导入 {n_files} 个来源到本地 TM。\n"
        "同一语言对下相同原文只保留首次出现（与库内已有句对也不重叠）。\n"
        f"CSV 若无语言列，缺省语言对：{sl or '?'} → {tl or '?'}\n\n"
        "是否继续？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if r != QMessageBox.Yes:
        return False
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        import translation_memory as tm

        result = tm.import_batch_from_files(
            paths,
            source_lang=sl,
            target_lang=tl,
            quality_gate=False,
            bidirectional=True,
        )
    except Exception as e:
        QMessageBox.warning(parent, "批量导入 TM", str(e))
        return False
    finally:
        QApplication.restoreOverrideCursor()
    if not result.get("ok"):
        QMessageBox.warning(
            parent,
            "批量导入 TM",
            result.get("reason") or "导入失败",
        )
        return False
    added = result.get("added", 0)
    skipped = result.get("skipped", 0)
    total = result.get("total_in_db", 0)
    dup = result.get("dup_skipped", 0)
    n_src = result.get("files", len(paths))
    if on_message:
        on_message(f"TM 批量 +{added}（{n_src} 源 · 库内 {total}）")
    detail_lines = [
        f"来源 {n_src} 个",
        f"解析 {result.get('parsed', 0)} 条",
        f"跨文件去重 {dup} 条",
        f"新增 {added} 条，跳过 {skipped} 条",
        f"当前 TM 总计 {total} 条",
    ]
    fr = result.get("file_results") or []
    if fr:
        detail_lines.append("")
        detail_lines.append("各文件：")
        for row in fr[:12]:
            if not row.get("ok", True):
                detail_lines.append(f"· {row.get('path', '?')}：失败")
                continue
            detail_lines.append(
                f"· {Path(row.get('path', '')).name}："
                f"解析 {row.get('parsed', 0)} · "
                f"去重 {row.get('dup_skipped', 0)} · "
                f"入队 {row.get('queued', 0)}"
            )
        if len(fr) > 12:
            detail_lines.append(f"…等共 {len(fr)} 个文件")
    QMessageBox.information(
        parent,
        "批量导入 TM",
        "\n".join(detail_lines),
    )
    if on_success:
        on_success()
    return True


def paste_import_tm(
    parent,
    source_lang: str = "",
    target_lang: str = "",
    *,
    on_message: Callable[[str], None] | None = None,
    on_success: Callable[[], None] | None = None,
) -> bool:
    sl, tl = (source_lang or "").strip(), (target_lang or "").strip()
    initial = QApplication.clipboard().text() or ""
    try:
        from tm_paste_import_dialog import open_tm_paste_import_dialog
    except ImportError:
        QMessageBox.warning(parent, "粘贴导入 TM", "粘贴导入模块未就绪。")
        return False
    result = open_tm_paste_import_dialog(
        parent,
        source_lang=sl,
        target_lang=tl,
        initial_text=initial,
    )
    if not result:
        return False
    added = int(result.get("added") or 0)
    skipped = int(result.get("skipped") or 0)
    dup = int(result.get("dup_skipped") or 0)
    total = int(result.get("total_in_db") or 0)
    if on_message:
        on_message(f"TM 粘贴 +{added}（库内 {total}）")
    QMessageBox.information(
        parent,
        "粘贴导入 TM",
        f"解析 {result.get('parsed', 0)} 条\n"
        f"表格内去重 {dup} 条\n"
        f"新增 {added} 条，跳过 {skipped} 条\n"
        f"当前 TM 总计 {total} 条",
    )
    if on_success:
        on_success()
    return True
