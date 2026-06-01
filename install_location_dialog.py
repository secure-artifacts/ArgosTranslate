"""
已安装后更改安装路径（在 PyQt 主界面中调用）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from portable_installer import default_install_dir, install_to, relocate_pointer
from portable_paths import install_pointer_path, is_install_root, load_install_pointer


class InstallLocationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("安装位置")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "启动器会记住安装文件夹。可改为已有完整安装目录，"
                "或在空文件夹中重新自动安装。"
            )
        )
        self._lbl = QLabel()
        self._lbl.setWordWrap(True)
        self._refresh_label()
        layout.addWidget(self._lbl)

        row = QHBoxLayout()
        btn_browse = QPushButton("选择文件夹…")
        btn_browse.clicked.connect(self._browse)
        btn_open = QPushButton("打开当前文件夹")
        btn_open.clicked.connect(self._open_folder)
        row.addWidget(btn_browse)
        row.addWidget(btn_open)
        layout.addLayout(row)

        btn_reinstall = QPushButton("在新文件夹中重新自动安装…")
        btn_reinstall.clicked.connect(self._reinstall_elsewhere)
        layout.addWidget(btn_reinstall)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def _refresh_label(self) -> None:
        cur = load_install_pointer()
        ptr = install_pointer_path()
        if cur:
            self._lbl.setText(f"当前安装：\n{cur}\n\n记录文件：\n{ptr}")
        else:
            self._lbl.setText(f"尚未记录安装路径。\n记录文件：\n{ptr}")

    def _browse(self) -> None:
        start = load_install_pointer() or default_install_dir()
        d = QFileDialog.getExistingDirectory(
            self, "选择安装文件夹", str(start)
        )
        if not d:
            return
        path = Path(d)
        if is_install_root(path):
            relocate_pointer(path)
            QMessageBox.information(
                self,
                "安装位置",
                f"已切换为：\n{path}\n\n请重新启动软件使路径生效。",
            )
            self._refresh_label()
            return
        if any(path.iterdir()) if path.is_dir() else False:
            QMessageBox.warning(
                self,
                "安装位置",
                "该文件夹已有内容，但不是有效的翻译器安装。\n"
                "请选择含 venv 与 terminology_bridge.py 的目录，"
                "或使用「重新自动安装」。",
            )
            return
        if QMessageBox.question(
            self,
            "安装位置",
            f"将自动安装到：\n{path}\n\n是否继续？",
        ) != QMessageBox.Yes:
            return
        try:
            install_to(path, lambda m: None)
            QMessageBox.information(
                self,
                "安装完成",
                f"已安装到：\n{path}\n\n请重新启动软件。",
            )
            self._refresh_label()
        except Exception as e:
            QMessageBox.critical(self, "安装失败", str(e))

    def _open_folder(self) -> None:
        import os
        import subprocess

        cur = load_install_pointer()
        if not cur:
            QMessageBox.information(self, "安装位置", "尚无已记录的安装路径。")
            return
        if sys.platform == "win32":
            os.startfile(str(cur))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(cur)])

    def _reinstall_elsewhere(self) -> None:
        start = default_install_dir()
        d = QFileDialog.getExistingDirectory(
            self, "选择新的安装文件夹", str(start)
        )
        if not d:
            return
        path = Path(d)
        if QMessageBox.question(
            self,
            "重新安装",
            f"将在以下位置全新安装（需联网）：\n{path}\n\n继续？",
        ) != QMessageBox.Yes:
            return
        try:
            install_to(path, lambda m: None)
            QMessageBox.information(
                self,
                "安装完成",
                f"已安装到：\n{path}\n\n请重新启动软件。",
            )
            self._refresh_label()
        except Exception as e:
            QMessageBox.critical(self, "安装失败", str(e))


def open_install_location_dialog(parent=None) -> None:
    dlg = InstallLocationDialog(parent)
    dlg.exec_()
