from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

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
