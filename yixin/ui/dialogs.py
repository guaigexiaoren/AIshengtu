from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..database import Database
from ..security import SecretStore, mask_secret, validate_api_key
from ..settings import (
    LOCAL_SAVE_LABELS,
    LOCAL_SAVE_MODES,
    AppSettings,
)
from .widgets import CompareWidget, load_scaled_pixmap


class SettingsDialog(QDialog):
    def __init__(
        self,
        secret_store: SecretStore,
        database: Database,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.secret_store = secret_store
        self.settings = AppSettings(database)
        self.setWindowTitle("设置")
        self.setMinimumWidth(650)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "API Key 仅保存在本机，并使用 Windows 当前用户加密。软件不会调用未确认的验证接口。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.current_label = QLabel()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("粘贴新的 API Key；留空不会覆盖现有密钥")
        form = QFormLayout()
        form.addRow("当前密钥", self.current_label)
        form.addRow("新密钥", self.key_edit)
        layout.addLayout(form)

        local_group = QGroupBox("本地保存位置")
        local_form = QFormLayout(local_group)
        self.local_mode_combo = QComboBox()
        for mode in LOCAL_SAVE_MODES:
            self.local_mode_combo.addItem(LOCAL_SAVE_LABELS[mode], mode)
        local_form.addRow("保存方式", self.local_mode_combo)
        fixed_row = QWidget()
        fixed_layout = QHBoxLayout(fixed_row)
        fixed_layout.setContentsMargins(0, 0, 0, 0)
        self.fixed_folder_edit = QLineEdit()
        self.fixed_folder_edit.setReadOnly(True)
        self.fixed_folder_edit.setPlaceholderText("选择固定保存文件夹")
        self.fixed_folder_button = QPushButton("选择文件夹")
        fixed_layout.addWidget(self.fixed_folder_edit, 1)
        fixed_layout.addWidget(self.fixed_folder_button)
        local_form.addRow("固定文件夹", fixed_row)
        local_hint = QLabel(
            "“每次询问”会记住上次目录；“参考图所在文件夹”使用任务中最后一张参考图的来源目录。"
        )
        local_hint.setWordWrap(True)
        local_hint.setStyleSheet("color:#69768c;")
        local_form.addRow(local_hint)
        layout.addWidget(local_group)

        warning = QLabel("日志和错误信息不会显示完整密钥或 Authorization 请求头。")
        warning.setStyleSheet("color:#69768c;")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        buttons = QHBoxLayout()
        self.clear_button = QPushButton("清除已保存密钥")
        self.clear_button.setObjectName("DangerButton")
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("PrimaryButton")
        close_button = QPushButton("关闭")
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self.save_button.clicked.connect(self._save)
        self.clear_button.clicked.connect(self._clear)
        self.fixed_folder_button.clicked.connect(self._choose_fixed_folder)
        self.local_mode_combo.currentIndexChanged.connect(self._update_folder_controls)
        close_button.clicked.connect(self.accept)
        self._refresh()

    def _refresh(self) -> None:
        self.current_label.setText(mask_secret(self.secret_store.load()))
        mode = self.settings.local_save_mode()
        index = self.local_mode_combo.findData(mode)
        self.local_mode_combo.setCurrentIndex(index if index >= 0 else 0)
        folder = self.settings.fixed_folder()
        self.fixed_folder_edit.setText(str(folder) if folder else "")
        self._update_folder_controls()

    def _update_folder_controls(self) -> None:
        is_fixed = self.local_mode_combo.currentData() == "fixed"
        self.fixed_folder_edit.setEnabled(is_fixed)
        self.fixed_folder_button.setEnabled(is_fixed)

    def _choose_fixed_folder(self) -> None:
        initial = self.fixed_folder_edit.text() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "选择固定保存文件夹", initial
        )
        if selected:
            self.fixed_folder_edit.setText(str(Path(selected).resolve()))

    def _save(self) -> None:
        mode = self.local_mode_combo.currentData()
        folder_text = self.fixed_folder_edit.text().strip()
        if mode == "fixed" and not folder_text:
            QMessageBox.warning(self, "缺少目录", "固定文件夹模式需要选择保存目录。")
            return
        if mode == "fixed" and not Path(folder_text).is_dir():
            QMessageBox.warning(self, "目录不可用", "固定保存目录不存在或不可访问。")
            return
        value = self.key_edit.text()
        if value.strip():
            try:
                validate_api_key(value)
                self.secret_store.save(value)
            except Exception as exc:
                QMessageBox.warning(self, "无法保存", str(exc))
                return
            self.key_edit.clear()
        self.settings.set_local_save_mode(mode)
        self.settings.set_fixed_folder(Path(folder_text) if folder_text else None)
        self._refresh()
        QMessageBox.information(
            self,
            "已保存",
            "设置已保存。API Key 仍使用 Windows DPAPI 加密。"
            if value.strip()
            else "本地保存设置已保存。",
        )

    def _clear(self) -> None:
        answer = QMessageBox.question(self, "确认清除", "确定清除本机保存的 API Key 吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.secret_store.clear()
        self._refresh()


class CompareDialog(QDialog):
    def __init__(
        self,
        left_path: Path,
        right_path: Path,
        *,
        left_label: str = "左侧",
        right_label: str = "右侧",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("图片对比")
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        labels = QHBoxLayout()
        labels.addWidget(QLabel(f"左侧：{left_label}"))
        labels.addStretch(1)
        labels.addWidget(QLabel(f"右侧：{right_label}"))
        layout.addLayout(labels)
        compare = CompareWidget()
        compare.set_images(left_path, right_path)
        layout.addWidget(compare, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)


class LibraryPickerDialog(QDialog):
    def __init__(
        self,
        database: Database,
        max_select: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.max_select = max_select
        self.setWindowTitle("从作品库选择参考图")
        self.resize(860, 600)
        layout = QVBoxLayout(self)
        tip = QLabel(f"最多还可选择 {max_select} 张。按住 Ctrl 可多选。")
        layout.addWidget(tip)
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_widget.setIconSize(QSize(150, 150))
        self.list_widget.setGridSize(QSize(190, 205))
        self.list_widget.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list_widget, 1)
        for preview in database.list_work_result_previews(limit=500):
            path = Path(preview["result_path"])
            if not path.is_file():
                continue
            item = QListWidgetItem(preview["title"])
            pixmap = load_scaled_pixmap(
                preview["preview_path"], QSize(150, 150)
            )
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(f"{preview['title']}\n{path.name}")
            self.list_widget.addItem(item)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        choose = QPushButton("添加所选")
        choose.setObjectName("PrimaryButton")
        buttons.addWidget(cancel)
        buttons.addWidget(choose)
        layout.addLayout(buttons)
        cancel.clicked.connect(self.reject)
        choose.clicked.connect(self._accept)

    def selected_paths(self) -> list[Path]:
        return [
            Path(item.data(Qt.ItemDataRole.UserRole))
            for item in self.list_widget.selectedItems()
        ]

    def _accept(self) -> None:
        if len(self.list_widget.selectedItems()) > self.max_select:
            QMessageBox.warning(
                self, "超过上限", f"本次最多只能再选择 {self.max_select} 张参考图。"
            )
            return
        if not self.list_widget.selectedItems():
            QMessageBox.information(self, "尚未选择", "请先选择至少一张图片。")
            return
        self.accept()


class TemplateManagerDialog(QDialog):
    def __init__(
        self,
        database: Database,
        *,
        current_prompt: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.current_prompt = current_prompt
        self.selected_prompt: str | None = None
        self.setWindowTitle("提示词模板")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, 1)
        buttons = QHBoxLayout()
        add = QPushButton("新建/覆盖")
        edit = QPushButton("编辑")
        delete = QPushButton("删除")
        delete.setObjectName("DangerButton")
        use = QPushButton("使用模板")
        use.setObjectName("PrimaryButton")
        buttons.addWidget(add)
        buttons.addWidget(edit)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        buttons.addWidget(use)
        layout.addLayout(buttons)
        add.clicked.connect(self._add)
        edit.clicked.connect(self._edit)
        delete.clicked.connect(self._delete)
        use.clicked.connect(self._use)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._use())
        self._refresh()

    def _refresh(self) -> None:
        self.list_widget.clear()
        for template in self.database.list_templates():
            item = QListWidgetItem(template["name"])
            item.setData(Qt.ItemDataRole.UserRole, template)
            prompt_preview = template["prompt"].strip().replace("\n", " ")
            item.setToolTip(prompt_preview[:300])
            self.list_widget.addItem(item)

    def _selected(self) -> dict | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _ask(self, title: str, name: str, prompt: str) -> tuple[str, str] | None:
        new_name, ok = QInputDialog.getText(self, title, "模板名称", text=name)
        if not ok or not new_name.strip():
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(620, 420)
        form = QVBoxLayout(dialog)
        form.addWidget(QLabel("提示词"))
        editor = QTextEdit()
        editor.setPlainText(prompt)
        form.addWidget(editor, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("取消")
        save = QPushButton("保存")
        save.setObjectName("PrimaryButton")
        row.addWidget(cancel)
        row.addWidget(save)
        form.addLayout(row)
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return new_name.strip(), editor.toPlainText()

    def _add(self) -> None:
        result = self._ask("保存提示词模板", "", self.current_prompt)
        if not result:
            return
        self.database.save_template(*result)
        self._refresh()

    def _edit(self) -> None:
        template = self._selected()
        if not template:
            return
        result = self._ask("编辑提示词模板", template["name"], template["prompt"])
        if not result:
            return
        new_name, prompt = result
        self.database.save_template(new_name, prompt)
        if new_name != template["name"]:
            self.database.delete_template(template["id"])
        self._refresh()

    def _delete(self) -> None:
        template = self._selected()
        if not template:
            return
        answer = QMessageBox.question(
            self, "删除模板", f"确定删除模板“{template['name']}”吗？"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.database.delete_template(template["id"])
            self._refresh()

    def _use(self) -> None:
        template = self._selected()
        if not template:
            return
        self.selected_prompt = template["prompt"]
        self.accept()
