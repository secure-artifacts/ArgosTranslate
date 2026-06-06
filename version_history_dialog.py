"""
从 GitHub Releases 选择历史版本下载安装（支持降级）。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app_version import APP_NAME, compare_versions
from github_update import (
    ReleaseInfo,
    download_and_apply_release,
    fetch_all_releases,
    github_repo,
    installed_version,
)
from portable_paths import find_portable_root, is_install_root
from portable_updater import restart_application


def _format_published_at(iso: str) -> str:
    text = (iso or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return text[:10]


class _HistoryWorker(QThread):
    status = pyqtSignal(str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task: str, release: ReleaseInfo | None = None) -> None:
        super().__init__()
        self._task = task
        self._release = release
        self._install_root = find_portable_root()

    def run(self) -> None:
        try:
            if self._task == "list":
                releases = fetch_all_releases()
                self.finished_ok.emit(releases)
            elif self._task == "apply" and self._release is not None:
                count, errors, old_v, new_v = download_and_apply_release(
                    self._release,
                    self._install_root,
                    progress=lambda m: self.status.emit(m),
                    force=True,
                )
                self.finished_ok.emit((count, errors, old_v, new_v))
            else:
                self.failed.emit("未知任务")
        except Exception as e:
            self.failed.emit(str(e))


class VersionHistoryDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("历史版本")
        self.setMinimumSize(520, 420)
        self._releases: list[ReleaseInfo] = []
        self._worker: _HistoryWorker | None = None
        self._restarting = False

        layout = QVBoxLayout(self)
        root = find_portable_root()
        local = installed_version(root)
        loc = str(root) if is_install_root(root) else "（未检测到安装目录）"
        self._lbl_info = QLabel(
            f"{APP_NAME}\n"
            f"当前版本：{local}\n"
            f"更新源：GitHub {github_repo()}\n"
            f"安装目录：{loc}\n\n"
            "选择任意历史版本安装。若低于当前版本，将自动删除较新版本新增的程序文件，"
            "用户数据（术语库、语言包、缓存等）会保留。"
        )
        self._lbl_info.setWordWrap(True)
        layout.addWidget(self._lbl_info)

        self._lbl_status = QLabel("正在加载版本列表…")
        self._lbl_status.setWordWrap(True)
        layout.addWidget(self._lbl_status)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list, stretch=1)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setPlaceholderText("Release 说明将显示在这里…")
        self._notes.setMaximumHeight(120)
        layout.addWidget(self._notes)

        row = QHBoxLayout()
        self._btn_refresh = QPushButton("刷新列表")
        self._btn_refresh.clicked.connect(self._load_list)
        self._btn_apply = QPushButton("下载并安装所选版本")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_release = QPushButton("在浏览器中打开")
        self._btn_release.setEnabled(False)
        self._btn_release.clicked.connect(self._open_release_page)
        row.addWidget(self._btn_refresh)
        row.addWidget(self._btn_apply)
        row.addWidget(self._btn_release)
        layout.addLayout(row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self._load_list()

    def _current_release(self) -> ReleaseInfo | None:
        row = self._list.currentRow()
        if row < 0 or row >= len(self._releases):
            return None
        return self._releases[row]

    def _set_busy(self, busy: bool) -> None:
        self._btn_refresh.setEnabled(not busy)
        self._list.setEnabled(not busy)
        if busy:
            self._btn_apply.setEnabled(False)
            self._btn_release.setEnabled(False)
        else:
            rel = self._current_release()
            self._btn_apply.setEnabled(rel is not None)
            self._btn_release.setEnabled(rel is not None)

    def _load_list(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._lbl_status.setText("正在从 GitHub 获取历史版本…")
        self._list.clear()
        self._notes.clear()
        self._worker = _HistoryWorker("list")
        self._worker.status.connect(self._lbl_status.setText)
        self._worker.finished_ok.connect(self._on_list_ok)
        self._worker.failed.connect(self._on_worker_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_list_ok(self, result: object) -> None:
        releases: list[ReleaseInfo] = result  # type: ignore[assignment]
        self._releases = releases
        local = installed_version()
        self._list.clear()
        for rel in releases:
            when = _format_published_at(rel.published_at)
            suffix = ""
            cmp = compare_versions(rel.version, local)
            if cmp == 0:
                suffix = "  ← 当前"
            elif cmp > 0:
                suffix = "  （较新）"
            else:
                suffix = "  （较旧）"
            label = f"v{rel.version}"
            if when:
                label += f"  ·  {when}"
            label += suffix
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, rel.version)
            self._list.addItem(item)
        if releases:
            self._list.setCurrentRow(0)
            self._lbl_status.setText(f"共 {len(releases)} 个可安装版本。")
        else:
            self._lbl_status.setText("未找到带更新包的 Release。")

    def _on_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._releases):
            self._notes.clear()
            self._btn_apply.setEnabled(False)
            self._btn_release.setEnabled(False)
            return
        rel = self._releases[row]
        self._notes.setPlainText(rel.body or "（无 Release 说明）")
        self._btn_apply.setEnabled(True)
        self._btn_release.setEnabled(True)

    def _on_apply(self) -> None:
        rel = self._current_release()
        if rel is None:
            return
        local = installed_version()
        cmp = compare_versions(rel.version, local)
        if cmp == 0:
            extra = "将重新安装当前版本。"
        elif cmp < 0:
            extra = (
                f"将从 {local} 降级到 {rel.version}。\n"
                "较新版本新增的程序文件将被自动删除，用户数据会保留。"
            )
        else:
            extra = f"将从 {local} 升级到 {rel.version}。"
        if (
            QMessageBox.question(
                self,
                "安装所选版本",
                f"将从 GitHub 下载并安装 v{rel.version}。\n"
                f"{extra}\n\n"
                "安装过程中请勿关闭本窗口。\n"
                "完成后将自动重启软件。\n\n"
                "是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._lbl_status.setText(f"正在下载 v{rel.version}…")
        self._worker = _HistoryWorker("apply", rel)
        self._worker.status.connect(self._lbl_status.setText)
        self._worker.finished_ok.connect(self._on_apply_ok)
        self._worker.failed.connect(self._on_worker_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_apply_ok(self, result: object) -> None:
        count, errors, old_v, new_v = result  # type: ignore[misc]
        if errors:
            QMessageBox.warning(
                self,
                "安装完成（部分失败）",
                f"版本 {old_v} → {new_v}\n"
                f"已处理 {count} 个文件，{len(errors)} 项失败。\n\n"
                + "\n".join(errors[:8]),
            )
            return
        root = find_portable_root()
        self._restarting = True
        self._lbl_info.setText(
            self._lbl_info.text().replace(
                f"当前版本：{old_v}", f"当前版本：{new_v}"
            )
        )
        self._lbl_status.setText(
            f"安装完成：{old_v} → {new_v}（已处理 {count} 个文件），正在重启…"
        )
        self._schedule_restart(root)

    def _open_release_page(self) -> None:
        rel = self._current_release()
        if rel and rel.html_url:
            QDesktopServices.openUrl(rel.html_url)

    def _on_worker_fail(self, msg: str) -> None:
        self._lbl_status.setText(f"失败：{msg}")
        QMessageBox.warning(self, "历史版本", msg)

    def _on_worker_finished(self) -> None:
        if self._restarting:
            return
        self._set_busy(False)

    def _schedule_restart(self, install_root: Path) -> None:
        if not is_install_root(install_root):
            QMessageBox.warning(
                self,
                "安装完成",
                "无法自动重启：未找到安装目录。\n请手动重新打开软件。",
            )
            return
        if not restart_application(install_root):
            QMessageBox.warning(
                self,
                "安装完成",
                "无法自动重启。\n请手动运行 run_gui.bat 或重新打开软件。",
            )
            return
        self.accept()
        QTimer.singleShot(300, _exit_application_after_update)


def _exit_application_after_update() -> None:
    import sys

    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.quit()
    sys.exit(0)


def open_version_history_dialog(parent=None) -> None:
    dlg = VersionHistoryDialog(parent)
    dlg.exec_()
