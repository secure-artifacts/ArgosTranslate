"""
首次启动 / 菜单：在软件内下载 Ollama 引擎与 Qwen 翻译模型。
"""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

import ollama_setup as setup
from ollama_translate import model_name, use_ollama_backend


class _SetupWorker(QThread):
    status = pyqtSignal(str)
    log_line = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, task: str, portable_root: Path, parent=None):
        super().__init__(parent)
        self.task = task
        self.portable_root = portable_root

    def run(self) -> None:
        try:
            if self.task == "download_installer":
                setup.download_ollama_installer(
                    self.portable_root,
                    status_cb=self.status.emit,
                    progress_cb=lambda a, b: self.progress.emit(a, b),
                )
                self.finished_ok.emit()
            elif self.task == "pull_model":
                setup.pull_model(
                    model_name(),
                    status_cb=self.status.emit,
                    line_cb=self.log_line.emit,
                    progress_cb=lambda a, b: self.progress.emit(a, b),
                )
                self.finished_ok.emit()
            elif self.task == "ensure_running":
                ok = setup.ensure_ollama_running(status_cb=self.status.emit)
                if ok:
                    self.finished_ok.emit()
                else:
                    self.failed.emit("无法启动 Ollama，请从开始菜单手动打开 Ollama。")
            else:
                self.failed.emit(f"未知任务: {self.task}")
        except Exception as exc:
            self.failed.emit(str(exc))


class OllamaSetupDialog(QDialog):
    """引导用户在本机安装 Ollama 并下载 Qwen 模型。"""

    def __init__(self, parent=None, *, portable_root: Path | None = None) -> None:
        super().__init__(parent)
        self._root = portable_root or setup.portable_root()
        self._worker: _SetupWorker | None = None
        self.setWindowTitle("下载翻译引擎")
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "本软件使用 <b>100% 本地</b> 的 Ollama + Qwen 2.5 进行翻译，数据不会上传。\n"
            "首次使用需在本机下载两部分（只需一次）：\n"
            "① Ollama 引擎（约 2 GB）　② 翻译模型 Qwen 2.5 7B（约 4.7 GB）"
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.RichText)
        layout.addWidget(intro)

        self._lbl_engine = QLabel()
        self._lbl_engine.setWordWrap(True)
        layout.addWidget(self._lbl_engine)

        row1 = QHBoxLayout()
        self._btn_download_engine = QPushButton("① 下载并安装 Ollama 引擎")
        self._btn_download_engine.clicked.connect(self._on_download_engine)
        self._btn_start_engine = QPushButton("启动 Ollama")
        self._btn_start_engine.clicked.connect(self._on_start_engine)
        row1.addWidget(self._btn_download_engine)
        row1.addWidget(self._btn_start_engine)
        layout.addLayout(row1)

        self._lbl_model = QLabel()
        self._lbl_model.setWordWrap(True)
        layout.addWidget(self._lbl_model)

        self._btn_download_model = QPushButton("② 下载翻译模型")
        self._btn_download_model.clicked.connect(self._on_download_model)
        layout.addWidget(self._btn_download_model)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        self._status = QLabel("就绪")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("下载进度…")
        layout.addWidget(self._log)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_close = QPushButton("完成")
        self._btn_close.clicked.connect(self.accept)
        self._btn_later = QPushButton("稍后")
        self._btn_later.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_later)
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

        self._refresh_status()

    def _refresh_status(self) -> None:
        st = setup.get_setup_status()
        m = str(st["model"])
        if st["ollama_installed"]:
            if st["ollama_running"]:
                eng = "✅ Ollama 引擎：已安装且正在运行"
            else:
                eng = "⚠️ Ollama 引擎：已安装，但未运行（请点「启动 Ollama」）"
        else:
            eng = "❌ Ollama 引擎：未安装"
        self._lbl_engine.setText(eng)

        if st["model_ready"]:
            mod = f"✅ 翻译模型 {m}：已下载，可离线使用"
        else:
            mod = f"❌ 翻译模型 {m}：未下载"
        self._lbl_model.setText(mod)

        ready = bool(st["ollama_running"] and st["model_ready"])
        self._btn_close.setEnabled(ready)
        self._btn_close.setText("完成" if ready else "完成（需先完成上面两步）")
        self._btn_download_model.setEnabled(bool(st["ollama_running"]))
        self._btn_start_engine.setEnabled(bool(st["ollama_installed"] and not st["ollama_running"]))

    def _set_busy(self, busy: bool) -> None:
        for w in (
            self._btn_download_engine,
            self._btn_start_engine,
            self._btn_download_model,
            self._btn_later,
        ):
            w.setEnabled(not busy)
        if not busy:
            self._refresh_status()

    def _append_log(self, line: str) -> None:
        self._log.append(line)
        sb = self._log.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())

    def _on_worker_status(self, msg: str) -> None:
        self._status.setText(msg)

    def _on_worker_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, total)
        self._progress.setValue(min(current, total))
        if total == 100:
            self._progress.setFormat(f"{current}%")

    def _start_worker(self, task: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._progress.setRange(0, 0)
        self._progress.setFormat("")
        self._worker = _SetupWorker(task, self._root, self)
        self._worker.status.connect(self._on_worker_status)
        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished_ok.connect(self._on_worker_ok)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_ok(self) -> None:
        self._worker = None
        self._progress.setRange(0, 100)
        self._progress.setValue(100)
        self._set_busy(False)
        self._refresh_status()

    def _on_worker_failed(self, msg: str) -> None:
        self._worker = None
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._set_busy(False)
        self._refresh_status()
        QMessageBox.warning(self, "下载翻译引擎", msg)

    def _on_download_engine(self) -> None:
        if setup.is_ollama_installed():
            reply = QMessageBox.question(
                self,
                "下载翻译引擎",
                "Ollama 似乎已安装。仍要重新下载安装包吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        def after_download() -> None:
            installer = setup.ollama_installer_cache_path(self._root)
            self._status.setText("正在打开安装程序，请按提示完成安装…")
            setup.run_ollama_installer(installer, silent=False)
            QMessageBox.information(
                self,
                "安装 Ollama",
                "安装程序已打开。\n\n"
                "请完成安装后点击「启动 Ollama」，或从开始菜单打开 Ollama。\n"
                "安装完成后返回本窗口继续下载翻译模型。",
            )
            self._worker = None
            self._set_busy(False)
            self._refresh_status()

        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._progress.setRange(0, 0)
        self._worker = _SetupWorker("download_installer", self._root, self)
        self._worker.status.connect(self._on_worker_status)
        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished_ok.connect(after_download)
        self._worker.start()

    def _on_start_engine(self) -> None:
        self._start_worker("ensure_running")

    def _on_download_model(self) -> None:
        if not setup.is_ollama_server_running():
            QMessageBox.information(
                self,
                "下载翻译模型",
                "请先安装并启动 Ollama，再下载模型。",
            )
            return
        self._start_worker("pull_model")


def maybe_show_setup_dialog(parent, portable_root: Path | None = None) -> None:
    if not use_ollama_backend():
        return
    if not setup.needs_setup():
        return
    dlg = OllamaSetupDialog(parent, portable_root=portable_root)
    dlg.exec_()


def open_setup_dialog(parent, portable_root: Path | None = None) -> None:
    dlg = OllamaSetupDialog(parent, portable_root=portable_root)
    dlg.exec_()
