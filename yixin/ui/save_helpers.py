from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..local_export import LocalImageExporter
from ..settings import (
    LOCAL_SAVE_ASK,
    LOCAL_SAVE_FIXED,
    LOCAL_SAVE_REFERENCE,
    AppSettings,
)


class LocalSaveController:
    def __init__(
        self,
        parent: QWidget,
        exporter: LocalImageExporter,
        settings: AppSettings,
    ) -> None:
        self.parent = parent
        self.exporter = exporter
        self.settings = settings

    def save(self, task_id: int, result_id: int) -> Path | None:
        mode = self.settings.local_save_mode()
        directory: Path | None = None
        if mode != LOCAL_SAVE_ASK:
            directory = self.exporter.preferred_directory(task_id)
        if directory is None:
            if mode == LOCAL_SAVE_REFERENCE:
                QMessageBox.information(
                    self.parent,
                    "需要选择保存位置",
                    "没有找到可用的参考图来源目录，请选择本次保存文件夹。",
                )
            elif mode == LOCAL_SAVE_FIXED:
                QMessageBox.information(
                    self.parent,
                    "固定文件夹不可用",
                    "设置的固定文件夹不存在或不可访问，请重新选择。",
                )
            initial = self.settings.last_folder()
            initial_text = str(initial) if initial and initial.is_dir() else ""
            selected = QFileDialog.getExistingDirectory(
                self.parent, "选择本地保存文件夹", initial_text
            )
            if not selected:
                return None
            directory = Path(selected).resolve()
            if mode == LOCAL_SAVE_FIXED:
                self.settings.set_fixed_folder(directory)
        return self.exporter.save_result(task_id, result_id, directory)


class SavedPathToast(QFrame):
    AUTO_HIDE_MS = 3000

    def __init__(
        self,
        host: QWidget,
        path: Path,
        *,
        title: str = "已保存到本地",
    ) -> None:
        super().__init__(host)
        self.host = host
        self.path = Path(path)
        self.setObjectName("SavedPathToast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#SavedPathToast { background:#152238; border:1px solid #36527a;"
            " border-radius:10px; }"
            "QLabel#ToastTitle { color:#ffffff; font-weight:700; }"
            "QLabel#ToastFile { color:#c7d3e8; font-size:11px; }"
            "QPushButton { background:#edf2f9; color:#243044; padding:5px 9px;"
            " border-radius:6px; border:none; }"
        )
        self.setToolTip(str(self.path))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)
        labels = QVBoxLayout()
        labels.setSpacing(1)
        title_label = QLabel(title)
        title_label.setObjectName("ToastTitle")
        file_label = QLabel(self.path.name)
        file_label.setObjectName("ToastFile")
        file_label.setMaximumWidth(280)
        file_label.setToolTip(str(self.path))
        labels.addWidget(title_label)
        labels.addWidget(file_label)
        layout.addLayout(labels, 1)
        self.open_button = QPushButton("打开文件夹")
        self.open_button.clicked.connect(self._open_folder)
        layout.addWidget(self.open_button)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(self.AUTO_HIDE_MS)
        self.timer.timeout.connect(self.dismiss)

    def show_at_bottom_right(self) -> None:
        self.adjustSize()
        bottom_offset = 24
        status_bar = getattr(self.host, "statusBar", None)
        if callable(status_bar):
            try:
                bottom_offset += status_bar().height()
            except Exception:
                pass
        x = max(16, self.host.width() - self.width() - 24)
        y = max(16, self.host.height() - self.height() - bottom_offset)
        self.move(x, y)
        self.show()
        self.raise_()
        self.timer.start()

    def _open_folder(self) -> None:
        folder = self.path if self.path.is_dir() else self.path.parent
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self.dismiss()
            return
        QMessageBox.warning(
            self.host,
            "无法打开",
            f"系统未能打开文件夹：\n{folder}",
        )

    def dismiss(self) -> None:
        self.timer.stop()
        if getattr(self.host, "_saved_path_toast", None) is self:
            self.host._saved_path_toast = None
        self.hide()
        self.deleteLater()


def show_saved_toast(
    parent: QWidget,
    path: Path,
    *,
    title: str = "已保存到本地",
) -> SavedPathToast:
    host = parent.window()
    previous = getattr(host, "_saved_path_toast", None)
    if isinstance(previous, SavedPathToast):
        previous.dismiss()
    toast = SavedPathToast(host, path, title=title)
    host._saved_path_toast = toast
    toast.show_at_bottom_right()
    return toast


def show_saved_path(
    parent: QWidget,
    *,
    title: str,
    message: str,
    path: Path,
) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(f"{message}\n\n保存位置：\n{path}")
    open_button = box.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
    box.addButton("关闭", QMessageBox.ButtonRole.AcceptRole)
    box.exec()
    if box.clickedButton() is open_button:
        folder = path if path.is_dir() else path.parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(parent, "无法打开", f"系统未能打开文件夹：\n{folder}")
