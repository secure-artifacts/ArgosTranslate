"""
已安装后查看 / 更改安装路径（在 PyQt 主界面中调用）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from portable_installer import default_install_dir, install_to, relocate_pointer
from portable_paths import (
    find_portable_root,
    install_pointer_path,
    is_install_root,
    load_install_pointer,
)


class InstallLocationDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("安装位置")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        layout.addWidget(
            QLabel(
                "程序文件与 venv 所在文件夹。更改路径后需重新启动软件；"
                "语言包、术语库等用户数据保存在该目录下的 data/ 中。"
            )
        )

        layout.addWidget(QLabel("当前安装路径："))
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("（尚未检测到有效安装）")
        layout.addWidget(self._path_edit)

        path_row = QHBoxLayout()
        btn_copy = QPushButton("复制路径")
        btn_copy.clicked.connect(self._copy_path)
        btn_open = QPushButton("打开文件夹")
        btn_open.clicked.connect(self._open_folder)
        path_row.addWidget(btn_copy)
        path_row.addWidget(btn_open)
        path_row.addStretch()
        layout.addLayout(path_row)

        self._lbl_meta = QLabel()
        self._lbl_meta.setWordWrap(True)
        self._lbl_meta.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(self._lbl_meta)

        action_row = QHBoxLayout()
        btn_change = QPushButton("更改安装路径…")
        btn_change.setToolTip(
            "切换到已有完整安装目录，或在空文件夹中自动安装"
        )
        btn_change.clicked.connect(self._change_path)
        btn_reinstall = QPushButton("在新文件夹重新安装…")
        btn_reinstall.setToolTip("在空文件夹中全新安装（需联网）")
        btn_reinstall.clicked.connect(self._reinstall_elsewhere)
        action_row.addWidget(btn_change)
        action_row.addWidget(btn_reinstall)
        action_row.addStretch()
        layout.addLayout(action_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self._refresh_view()

    def _runtime_root(self) -> Path | None:
        try:
            root = find_portable_root()
        except OSError:
            return None
        if is_install_root(root):
            return root.resolve()
        return None

    def _refresh_view(self) -> None:
        runtime = self._runtime_root()
        pointer = load_install_pointer()
        ptr_file = install_pointer_path()
        if runtime is not None:
            self._path_edit.setText(str(runtime))
        elif pointer is not None:
            self._path_edit.setText(str(pointer))
        else:
            self._path_edit.clear()

        lines: list[str] = [f"路径记录文件：{ptr_file}"]
        if pointer and runtime and pointer.resolve() != runtime.resolve():
            lines.append(
                f"记录路径与当前运行路径不一致。\n"
                f"记录：{pointer}\n"
                f"运行：{runtime}"
            )
        elif not pointer:
            lines.append("尚未写入路径记录；下次用安装 exe 启动时会记住所选文件夹。")
        self._lbl_meta.setText("\n".join(lines))

    def _current_path(self) -> Path | None:
        text = (self._path_edit.text() or "").strip()
        if not text:
            return None
        p = Path(text)
        return p if is_install_root(p) else None

    def _copy_path(self) -> None:
        text = (self._path_edit.text() or "").strip()
        if not text:
            QMessageBox.information(self, "安装位置", "当前没有可复制的安装路径。")
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "安装位置", "路径已复制到剪贴板。")

    def _change_path(self) -> None:
        start = self._current_path() or load_install_pointer() or default_install_dir()
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
            self._refresh_view()
            return
        if path.is_dir() and any(path.iterdir()):
            QMessageBox.warning(
                self,
                "安装位置",
                "该文件夹已有内容，但不是有效的翻译器安装。\n\n"
                "请选择已含 venv 与 terminology_bridge.py 的目录，"
                "或选择空文件夹以自动安装。",
            )
            return
        if QMessageBox.question(
            self,
            "安装位置",
            f"将在以下空文件夹中自动安装（需联网，约 15～40 分钟）：\n\n"
            f"{path}\n\n是否继续？",
        ) != QMessageBox.Yes:
            return
        try:
            install_to(path, lambda m: None)
            QMessageBox.information(
                self,
                "安装完成",
                f"已安装到：\n{path}\n\n请重新启动软件。",
            )
            self._refresh_view()
        except Exception as e:
            QMessageBox.critical(self, "安装失败", str(e))

    def _open_folder(self) -> None:
        import os
        import subprocess

        cur = self._current_path()
        if cur is None:
            QMessageBox.information(self, "安装位置", "尚无有效的安装路径。")
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
        if path.is_dir() and any(path.iterdir()):
            if not is_install_root(path):
                if (
                    QMessageBox.question(
                        self,
                        "重新安装",
                        "该文件夹非空且不是现有安装。\n"
                        "继续将尝试覆盖/写入该目录，是否继续？",
                    )
                    != QMessageBox.Yes
                ):
                    return
            elif (
                QMessageBox.question(
                    self,
                    "重新安装",
                    f"该目录已是安装位置。\n\n"
                    f"{path}\n\n"
                    "继续将重新安装程序文件（保留 data/）。是否继续？",
                )
                != QMessageBox.Yes
            ):
                return
        elif (
            QMessageBox.question(
                self,
                "重新安装",
                f"将在以下位置安装（需联网）：\n\n{path}\n\n继续？",
            )
            != QMessageBox.Yes
        ):
            return
        try:
            install_to(path, lambda m: None)
            QMessageBox.information(
                self,
                "安装完成",
                f"已安装到：\n{path}\n\n请重新启动软件。",
            )
            self._refresh_view()
        except Exception as e:
            QMessageBox.critical(self, "安装失败", str(e))


def open_install_location_dialog(parent=None) -> None:
    dlg = InstallLocationDialog(parent)
    dlg.exec_()
