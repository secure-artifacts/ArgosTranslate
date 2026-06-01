"""
检查更新对话框（GitHub Releases）。
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app_version import APP_NAME
from github_update import (
    ReleaseInfo,
    check_for_update,
    download_and_apply_release,
    fetch_latest_release,
    github_repo,
    installed_version,
)
from portable_paths import find_portable_root, is_install_root


class _UpdateWorker(QThread):
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
            if self._task == "check":
                msg, rel = check_for_update(self._install_root)
                self.finished_ok.emit((msg, rel))
            elif self._task == "apply" and self._release is not None:
                count, errors, old_v, new_v = download_and_apply_release(
                    self._release,
                    self._install_root,
                    progress=lambda m: self.status.emit(m),
                )
                self.finished_ok.emit((count, errors, old_v, new_v))
            else:
                self.failed.emit("未知任务")
        except Exception as e:
            self.failed.emit(str(e))


class UpdateDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setMinimumSize(480, 360)
        self._release: ReleaseInfo | None = None
        self._worker: _UpdateWorker | None = None

        layout = QVBoxLayout(self)
        root = find_portable_root()
        loc = str(root) if is_install_root(root) else "（未检测到安装目录）"
        self._lbl_info = QLabel(
            f"{APP_NAME}\n"
            f"当前版本：{installed_version(root)}\n"
            f"更新源：GitHub {github_repo()}\n"
            f"安装目录：{loc}"
        )
        self._lbl_info.setWordWrap(True)
        layout.addWidget(self._lbl_info)

        self._lbl_status = QLabel("点击「检查更新」从 GitHub 获取最新版本。")
        self._lbl_status.setWordWrap(True)
        layout.addWidget(self._lbl_status)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setPlaceholderText("Release 说明将显示在这里…")
        self._notes.setMaximumHeight(140)
        layout.addWidget(self._notes)

        row = QHBoxLayout()
        self._btn_check = QPushButton("检查更新")
        self._btn_check.clicked.connect(self._on_check)
        self._btn_apply = QPushButton("下载并安装")
        self._btn_apply.setEnabled(False)
        self._btn_apply.clicked.connect(self._on_apply)
        self._btn_release = QPushButton("在浏览器中打开 Release")
        self._btn_release.setEnabled(False)
        self._btn_release.clicked.connect(self._open_release_page)
        row.addWidget(self._btn_check)
        row.addWidget(self._btn_apply)
        row.addWidget(self._btn_release)
        layout.addLayout(row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    def _set_busy(self, busy: bool) -> None:
        self._btn_check.setEnabled(not busy)
        can_apply = False
        if not busy and self._release is not None:
            from app_version import compare_versions

            can_apply = compare_versions(
                self._release.version, installed_version()
            ) > 0
        self._btn_apply.setEnabled(can_apply)
        self._btn_release.setEnabled(not busy and self._release is not None)

    def _on_check(self) -> None:
        self._start_worker("check")

    def _on_apply(self) -> None:
        if self._release is None:
            return
        if (
            QMessageBox.question(
                self,
                "安装更新",
                f"将从 GitHub 下载并安装 {self._release.version}。\n"
                "更新过程中请勿关闭本窗口。\n"
                "完成后请完全退出并重新打开软件。\n\n"
                "是否继续？",
            )
            != QMessageBox.Yes
        ):
            return
        self._start_worker("apply", self._release)

    def _open_release_page(self) -> None:
        if self._release and self._release.html_url:
            QDesktopServices.openUrl(self._release.html_url)

    def _start_worker(self, task: str, release: ReleaseInfo | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._lbl_status.setText("正在连接 GitHub…")
        self._worker = _UpdateWorker(task, release)
        self._worker.status.connect(self._lbl_status.setText)
        self._worker.finished_ok.connect(self._on_worker_ok)
        self._worker.failed.connect(self._on_worker_fail)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_ok(self, result: object) -> None:
        if self._worker is None:
            return
        if self._worker._task == "check":
            msg, rel = result  # type: ignore[misc]
            self._release = rel
            self._lbl_status.setText(str(msg))
            if rel:
                self._notes.setPlainText(rel.body or "（无 Release 说明）")
                self._btn_release.setEnabled(True)
                from app_version import compare_versions

                if compare_versions(rel.version, installed_version()) > 0:
                    self._btn_apply.setEnabled(True)
                else:
                    self._btn_apply.setEnabled(False)
        elif self._worker._task == "apply":
            count, errors, old_v, new_v = result  # type: ignore[misc]
            if errors:
                QMessageBox.warning(
                    self,
                    "更新完成（部分失败）",
                    f"版本 {old_v} → {new_v}\n"
                    f"已更新 {count} 个文件，{len(errors)} 项失败。\n\n"
                    + "\n".join(errors[:8]),
                )
            else:
                QMessageBox.information(
                    self,
                    "更新完成",
                    f"已更新 {count} 个文件。\n"
                    f"版本：{old_v} → {new_v}\n\n"
                    "请完全退出本程序后重新打开，以加载新版本。",
                )
                self._lbl_info.setText(
                    self._lbl_info.text().replace(
                        f"当前版本：{old_v}", f"当前版本：{new_v}"
                    )
                )

    def _on_worker_fail(self, msg: str) -> None:
        self._lbl_status.setText(f"失败：{msg}")
        QMessageBox.warning(self, "检查更新", msg)

    def _on_worker_finished(self) -> None:
        self._set_busy(False)
        if self._release is not None:
            from app_version import compare_versions

            self._btn_apply.setEnabled(
                compare_versions(self._release.version, installed_version()) > 0
            )
            self._btn_release.setEnabled(True)


def open_update_dialog(parent=None) -> None:
    dlg = UpdateDialog(parent)
    dlg.exec_()
