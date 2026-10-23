from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPoint, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QDrag, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    ASPECT_RATIOS,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MODEL,
    DEFAULT_RESOLUTION,
    MAX_BATCH_ASSETS,
    MODE_DRESS_UP,
    MODEL_OPTIONS,
    RESOLUTIONS,
)
from ..database import Database
from ..library import LibraryService
from ..models import ImageRequest, StoredImage
from ..security import SecretStore
from ..storage import FileStore, ImageValidationError
from ..worker import TaskWorker
from .crop import CropDialog
from .dialogs import LibraryPickerDialog, TemplateManagerDialog
from .widgets import (
    load_scaled_pixmap,
    natural_sort_key,
    scan_image_inputs,
)

DRESS_UP_MIME = "application/x-yixin-batch-dress-up-garment"
PAIR_CARD_MIN_WIDTH = 280
PAIR_CARD_GAP = 8
MIN_PAIR_COLUMNS = 2
MAX_PAIR_COLUMNS = 8
ROLE_LABELS = {
    "garment": "服装",
    "person": "人物",
}


@dataclass(frozen=True)
class DressPair:
    garment: StoredImage
    person: StoredImage

    @property
    def key(self) -> tuple[str, str]:
        return (self.garment.content_hash, self.person.content_hash)


class BatchAssetList(QListWidget):
    files_dropped = Signal(object)
    garment_dropped = Signal(str, int)

    def __init__(self, role: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.role = role
        self.setObjectName("ImageStrip")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setIconSize(QSize(82, 82))
        self.setGridSize(QSize(112, 126))
        self.setMinimumHeight(160)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.setWordWrap(True)
        self._drag_start: QPoint | None = None
        self._drag_row: int | None = None
        self._drag_active = False

    def refresh_assets(self, assets: Sequence[StoredImage]) -> None:
        selected_hash = None
        current = self.currentItem()
        if current:
            selected = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(selected, StoredImage):
                selected_hash = selected.content_hash

        self.blockSignals(True)
        self.clear()
        for index, image in enumerate(assets):
            item = QListWidgetItem(
                f"{ROLE_LABELS[self.role]} {index + 1}\n{image.original_name}"
            )
            pixmap = load_scaled_pixmap(image.path, self.iconSize())
            if not pixmap.isNull():
                item.setIcon(QIcon(pixmap))
            item.setData(Qt.ItemDataRole.UserRole, image)
            item.setToolTip(
                f"{ROLE_LABELS[self.role]} {index + 1}\n"
                f"{image.original_name}\n{image.path}"
            )
            self.addItem(item)
            if selected_hash and image.content_hash == selected_hash:
                self.setCurrentItem(item)
        self.blockSignals(False)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        if self.role != "garment" or event.button() != Qt.MouseButton.LeftButton:
            self._reset_drag()
            return
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self._drag_row = index.row()
            self._drag_start = event.position().toPoint()
            self._drag_active = False
        else:
            self._reset_drag()

    def mouseMoveEvent(self, event) -> None:
        position = event.position().toPoint()
        if (
            self.role == "garment"
            and self._drag_row is not None
            and self._drag_start is not None
        ):
            if (
                not self._drag_active
                and (position - self._drag_start).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._drag_active = True
                item = self.item(self._drag_row)
                image = item.data(Qt.ItemDataRole.UserRole) if item else None
                if isinstance(image, StoredImage):
                    drag = QDrag(self)
                    mime = QMimeData()
                    mime.setData(DRESS_UP_MIME, image.content_hash.encode("utf-8"))
                    mime.setText(image.original_name)
                    drag.setMimeData(mime)
                    pixmap = item.icon().pixmap(self.iconSize())
                    if not pixmap.isNull():
                        drag.setPixmap(pixmap)
                        drag.setHotSpot(pixmap.rect().center())
                    drag.exec(Qt.DropAction.CopyAction)
                self._reset_drag()
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._reset_drag()
        super().mouseReleaseEvent(event)

    def _reset_drag(self) -> None:
        self._drag_start = None
        self._drag_row = None
        self._drag_active = False

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls() or (
            self.role == "person" and mime.hasFormat(DRESS_UP_MIME)
        ):
            self._set_drop_highlight(True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
            return
        if self.role == "person" and mime.hasFormat(DRESS_UP_MIME):
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.setCurrentRow(index.row())
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_highlight(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_drop_highlight(False)
        mime = event.mimeData()
        if self.role == "person" and mime.hasFormat(DRESS_UP_MIME):
            index = self.indexAt(event.position().toPoint())
            if not index.isValid():
                event.ignore()
                return
            payload = bytes(mime.data(DRESS_UP_MIME)).decode("utf-8")
            self.garment_dropped.emit(payload, index.row())
            event.acceptProposedAction()
            return
        if mime.hasUrls():
            paths = [
                Path(url.toLocalFile())
                for url in mime.urls()
                if url.isLocalFile()
            ]
            if not paths:
                event.ignore()
                return
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        event.ignore()

    def _set_drop_highlight(self, active: bool) -> None:
        if active:
            self.setStyleSheet(
                "QListWidget#ImageStrip { border: 2px solid #3f73cb;"
                " background: #edf4ff; }"
            )
        else:
            self.setStyleSheet("")


class DressPairCard(QFrame):
    remove_requested = Signal(object)

    def __init__(
        self,
        pair: DressPair,
        position: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pair = pair
        self.setObjectName("DressPairCard")
        self.setMinimumHeight(144)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QFrame#DressPairCard { background:#f8fafd; border:1px solid #dce5f1;"
            " border-radius:9px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(5)

        header = QHBoxLayout()
        order = QLabel(f"配对 {position}")
        order.setStyleSheet("font-weight:700;color:#2e64c4;")
        remove = QPushButton("移除")
        remove.setObjectName("DangerButton")
        remove.setStyleSheet("padding: 3px 7px;")
        remove.clicked.connect(lambda: self.remove_requested.emit(self.pair))
        header.addWidget(order)
        header.addStretch(1)
        header.addWidget(remove)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(5)
        body.addStretch(1)
        body.addWidget(self._image_block(pair.garment, "服装"))
        arrow = QLabel("→")
        arrow.setStyleSheet("font-size:19px;color:#2e64c4;font-weight:700;")
        body.addWidget(arrow)
        body.addWidget(self._image_block(pair.person, "人物"))
        body.addStretch(1)
        layout.addLayout(body)

    @staticmethod
    def _image_block(image: StoredImage, role_label: str) -> QWidget:
        block = QWidget()
        block.setFixedWidth(96)
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        preview = QLabel()
        preview.setObjectName("DressPairThumbnail")
        preview.setFixedSize(68, 68)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = load_scaled_pixmap(image.path, QSize(66, 66))
        if not pixmap.isNull():
            preview.setPixmap(pixmap)
        display_name = (
            image.original_name
            if len(image.original_name) <= 12
            else f"{image.original_name[:6]}…{image.original_name[-4:]}"
        )
        name = QLabel(f"{role_label}：{display_name}")
        name.setObjectName("DressPairFileName")
        name.setFixedWidth(96)
        name.setWordWrap(True)
        name.setMaximumHeight(28)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setToolTip(image.original_name)
        name.setStyleSheet("color:#5d6b82;font-size:11px;")
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)
        return block


class BatchDressPage(QWidget):
    settings_requested = Signal()
    tasks_enqueued = Signal(int)
    templates_changed = Signal()

    def __init__(
        self,
        database: Database,
        file_store: FileStore,
        library_service: LibraryService,
        worker: TaskWorker,
        secret_store: SecretStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database = database
        self.file_store = file_store
        self.library_service = library_service
        self.worker = worker
        self.secret_store = secret_store
        self.garment_assets: list[StoredImage] = []
        self.person_assets: list[StoredImage] = []
        self.pairs: list[DressPair] = []
        self.selected_garment: StoredImage | None = None
        self.pair_columns = 4
        self._pair_layout_pending = False
        self._pair_panel_height = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.form_content = content
        scroll.setWidget(content)
        self.page_scroll = scroll

        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 4)
        layout.setSpacing(8)
        layout.addWidget(self._build_header())
        self.top_options_host = QWidget()
        top_options = QHBoxLayout(self.top_options_host)
        top_options.setContentsMargins(0, 0, 0, 0)
        top_options.setSpacing(12)
        self.settings_group = self._build_settings()
        self.prompt_group = self._build_prompt()
        top_options.addWidget(self.settings_group, 1)
        top_options.addWidget(self.prompt_group, 1)
        layout.addWidget(self.top_options_host)
        layout.addWidget(self._build_asset_columns(), 1)
        outer.addWidget(scroll, 5)
        self.pair_group = self._build_pairs()
        outer.addWidget(self.pair_group)
        self.submit_card = self._build_submit()
        outer.addWidget(self.submit_card)
        self.refresh_templates()
        QTimer.singleShot(0, self._update_pair_panel_height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_pair_panel_height)

    def _update_pair_panel_height(self) -> None:
        if not hasattr(self, "pair_group"):
            return
        page_height = self.height()
        target = 260 if page_height < 900 else max(260, round(page_height * 0.40))
        if target == self._pair_panel_height:
            return
        self._pair_panel_height = target
        self.pair_group.setFixedHeight(target)

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        title = QLabel("批量换装")
        title.setStyleSheet("font-size:22px;font-weight:700;color:#1f2d43;")
        subtitle = QLabel(
            "上传服装和人物素材，点击“服装 → 人物”或直接拖拽缩略图完成配对。"
        )
        subtitle.setStyleSheet("color:#6d7a91;")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return card

    def _build_settings(self) -> QWidget:
        card = QGroupBox("生成设置")
        card.setObjectName("Card")
        form = QFormLayout(card)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.model_combo = QComboBox()
        for name, model_id in MODEL_OPTIONS:
            self.model_combo.addItem(name, model_id)
        self.model_combo.setCurrentIndex(
            next(
                index
                for index, (_, model_id) in enumerate(MODEL_OPTIONS)
                if model_id == DEFAULT_MODEL
            )
        )
        form.addRow("模型", self.model_combo)

        params = QWidget()
        param_layout = QHBoxLayout(params)
        param_layout.setContentsMargins(0, 0, 0, 0)
        self.aspect_combo = QComboBox()
        for value in ASPECT_RATIOS:
            self.aspect_combo.addItem(value, value)
        self.aspect_combo.setCurrentText(DEFAULT_ASPECT_RATIO)
        self.resolution_combo = QComboBox()
        for value in RESOLUTIONS:
            self.resolution_combo.addItem(
                "自动（不发送）" if value == "auto" else value,
                value,
            )
        self.resolution_combo.setCurrentIndex(
            next(
                index
                for index, value in enumerate(RESOLUTIONS)
                if value == DEFAULT_RESOLUTION
            )
        )
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 4)
        self.count_spin.setValue(DEFAULT_BATCH_SIZE)
        param_layout.addWidget(QLabel("宽高比"))
        param_layout.addWidget(self.aspect_combo)
        param_layout.addSpacing(8)
        param_layout.addWidget(QLabel("分辨率"))
        param_layout.addWidget(self.resolution_combo)
        param_layout.addSpacing(8)
        param_layout.addWidget(QLabel("每对数量"))
        param_layout.addWidget(self.count_spin)
        param_layout.addStretch(1)
        form.addRow("参数", params)
        return card

    def _build_prompt(self) -> QWidget:
        card = QGroupBox("换装提示词")
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        template_row = QHBoxLayout()
        template_row.setSpacing(5)
        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(110)
        self.template_combo.addItem("选择提示词模板", None)
        apply_template = QPushButton("应用")
        save_template = QPushButton("保存当前")
        manage_templates = QPushButton("管理")
        for button in (apply_template, save_template, manage_templates):
            button.setStyleSheet("padding: 5px 8px;")
        template_row.addWidget(self.template_combo, 1)
        template_row.addWidget(apply_template)
        template_row.addWidget(save_template)
        template_row.addWidget(manage_templates)
        layout.addLayout(template_row)
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setMinimumHeight(96)
        self.prompt_edit.setMaximumHeight(110)
        self.prompt_edit.setPlaceholderText(
            "请描述换装要求。参考图顺序固定为：第 1 张是服装，第 2 张是人物。\n"
            "例如：将第 1 张图中的服装自然地穿到第 2 张图的人物身上，"
            "保持人物身份和姿态，准确还原服装颜色、材质与纹理。"
        )
        layout.addWidget(self.prompt_edit)
        apply_template.clicked.connect(self._apply_template)
        save_template.clicked.connect(self._quick_save_template)
        manage_templates.clicked.connect(self._manage_templates)
        return card

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_templates()

    def refresh_templates(self) -> None:
        if not hasattr(self, "template_combo"):
            return
        selected = self.template_combo.currentData()
        selected_id = selected.get("id") if selected else None
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItem("选择提示词模板", None)
        for template in self.database.list_templates():
            self.template_combo.addItem(template["name"], template)
        if selected_id is not None:
            for index in range(self.template_combo.count()):
                data = self.template_combo.itemData(index)
                if data and data.get("id") == selected_id:
                    self.template_combo.setCurrentIndex(index)
                    break
        self.template_combo.blockSignals(False)

    def _apply_template(self) -> None:
        template = self.template_combo.currentData()
        if template:
            self.prompt_edit.setPlainText(template["prompt"])

    def _quick_save_template(self) -> None:
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "提示词为空", "请先填写提示词。")
            return
        name, ok = QInputDialog.getText(self, "保存提示词模板", "模板名称")
        if not ok or not name.strip():
            return
        try:
            self.database.save_template(name, prompt)
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return
        self.refresh_templates()
        self.templates_changed.emit()

    def _manage_templates(self) -> None:
        dialog = TemplateManagerDialog(
            self.database,
            current_prompt=self.prompt_edit.toPlainText(),
            parent=self,
        )
        dialog.exec()
        templates_changed = bool(dialog.templates_changed)
        if dialog.selected_prompt:
            self.prompt_edit.setPlainText(dialog.selected_prompt)
        self.refresh_templates()
        if templates_changed:
            self.templates_changed.emit()

    def _build_asset_columns(self) -> QWidget:
        host = QWidget()
        self.asset_columns_host = host
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        garment_group, self.garment_list = self._make_asset_group("garment")
        person_group, self.person_list = self._make_asset_group("person")
        self.garment_group = garment_group
        self.person_group = person_group
        layout.addWidget(garment_group, 1)
        layout.addWidget(person_group, 1)

        self.garment_list.currentItemChanged.connect(
            self._garment_selection_changed
        )
        self.person_list.currentItemChanged.connect(
            self._person_selection_changed
        )
        self.person_list.itemClicked.connect(self._person_clicked)
        self.garment_list.files_dropped.connect(
            lambda paths: self._append_assets("garment", paths)
        )
        self.person_list.files_dropped.connect(
            lambda paths: self._append_assets("person", paths)
        )
        self.person_list.garment_dropped.connect(self._garment_dropped)
        return host

    def _make_asset_group(self, role: str) -> tuple[QWidget, BatchAssetList]:
        group = QGroupBox(f"{ROLE_LABELS[role]}素材（最多 {MAX_BATCH_ASSETS} 张）")
        group.setObjectName("Card")
        layout = QVBoxLayout(group)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        add_images = QPushButton("添加图片")
        add_folder = QPushButton("添加文件夹")
        add_library = QPushButton("作品库")
        crop = QPushButton("裁剪")
        restore = QPushButton("恢复")
        remove = QPushButton("移除所选")
        clear = QPushButton("清空")
        add_library.setToolTip("从作品库添加")
        for button in (
            add_images,
            add_folder,
            add_library,
            crop,
            restore,
            remove,
            clear,
        ):
            button.setStyleSheet("padding: 6px 8px;")
        buttons.addWidget(add_images)
        buttons.addWidget(add_folder)
        buttons.addWidget(add_library)
        buttons.addWidget(crop)
        buttons.addWidget(restore)
        buttons.addStretch(1)
        buttons.addWidget(remove)
        buttons.addWidget(clear)
        layout.addLayout(buttons)

        asset_list = BatchAssetList(role)
        layout.addWidget(asset_list, 1)
        count_label = QLabel(f"已选择 0 / {MAX_BATCH_ASSETS} 张")
        count_label.setStyleSheet("color:#6d7a91;")
        layout.addWidget(count_label)
        if role == "garment":
            self.garment_count_label = count_label
            self.garment_crop_button = crop
            self.garment_restore_button = restore
        else:
            self.person_count_label = count_label
            self.person_crop_button = crop
            self.person_restore_button = restore

        add_images.clicked.connect(lambda: self._add_image_files(role))
        add_folder.clicked.connect(lambda: self._add_image_folder(role))
        add_library.clicked.connect(lambda: self._add_library_images(role))
        crop.clicked.connect(lambda: self._crop_selected(role))
        restore.clicked.connect(lambda: self._restore_selected(role))
        remove.clicked.connect(lambda: self._remove_selected(role))
        clear.clicked.connect(lambda: self._clear_role(role))
        crop.setEnabled(False)
        restore.setEnabled(False)
        return group, asset_list

    def _build_pairs(self) -> QWidget:
        group = QGroupBox("配对任务")
        group.setObjectName("Card")
        layout = QVBoxLayout(group)
        top = QHBoxLayout()
        self.pair_count_label = QLabel("已建立 0 个配对")
        self.pair_count_label.setStyleSheet("color:#2e64c4;font-weight:600;")
        clear_pairs = QPushButton("清空配对")
        top.addWidget(self.pair_count_label)
        top.addStretch(1)
        top.addWidget(clear_pairs)
        layout.addLayout(top)

        self.pair_scroll = QScrollArea()
        self.pair_scroll.setWidgetResizable(True)
        self.pair_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.pair_scroll.setMinimumHeight(200)
        self.pair_host = QWidget()
        self.pair_grid = QGridLayout(self.pair_host)
        self.pair_grid.setContentsMargins(0, 0, 0, 0)
        self.pair_grid.setVerticalSpacing(8)
        self.pair_grid.setHorizontalSpacing(8)
        self.pair_grid.setSpacing(8)
        self.pair_scroll.setWidget(self.pair_host)
        self.pair_scroll.viewport().installEventFilter(self)
        layout.addWidget(self.pair_scroll, 1)
        group.setMinimumHeight(260)
        group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        clear_pairs.clicked.connect(self._clear_pairs)
        self._refresh_pairs()
        return group

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "pair_scroll", None) or (
            hasattr(self, "pair_scroll")
            and watched is self.pair_scroll.viewport()
        ):
            if event.type() == QEvent.Type.Resize:
                self._schedule_pair_layout()
        return super().eventFilter(watched, event)

    def _schedule_pair_layout(self) -> None:
        if self._pair_layout_pending:
            return
        self._pair_layout_pending = True
        QTimer.singleShot(0, self._update_pair_columns)

    def _update_pair_columns(self) -> None:
        self._pair_layout_pending = False
        width = self.pair_scroll.viewport().width()
        columns = max(
            MIN_PAIR_COLUMNS,
            min(
                MAX_PAIR_COLUMNS,
                (max(1, width) + PAIR_CARD_GAP)
                // (PAIR_CARD_MIN_WIDTH + PAIR_CARD_GAP),
            ),
        )
        if columns != self.pair_columns:
            self.pair_columns = columns
            self._refresh_pairs()

    def _build_submit(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QHBoxLayout(card)
        self.feedback_label = QLabel(
            "先选择服装，再点击人物；也可把服装缩略图直接拖到人物上。"
        )
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("color:#6d7a91;")
        self.generate_button = QPushButton("生成全部配对并加入队列")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.setMinimumHeight(42)
        self.generate_button.clicked.connect(self._enqueue_all)
        layout.addWidget(self.feedback_label, 1)
        layout.addWidget(self.generate_button)
        return card

    def _assets_for(self, role: str) -> list[StoredImage]:
        return self.garment_assets if role == "garment" else self.person_assets

    def _asset_list_for(self, role: str) -> BatchAssetList:
        return self.garment_list if role == "garment" else self.person_list

    def _refresh_role(self, role: str) -> None:
        assets = self._assets_for(role)
        self._asset_list_for(role).refresh_assets(assets)
        count_label = (
            self.garment_count_label
            if role == "garment"
            else self.person_count_label
        )
        count_label.setText(f"已选择 {len(assets)} / {MAX_BATCH_ASSETS} 张")
        if role == "garment" and self.selected_garment not in assets:
            self.selected_garment = None
        self._update_asset_actions()

    def _update_asset_actions(self) -> None:
        for role in ("garment", "person"):
            asset_list = self._asset_list_for(role)
            assets = self._assets_for(role)
            row = asset_list.currentRow()
            has_selection = 0 <= row < len(assets)
            crop_button = (
                self.garment_crop_button
                if role == "garment"
                else self.person_crop_button
            )
            restore_button = (
                self.garment_restore_button
                if role == "garment"
                else self.person_restore_button
            )
            image = assets[row] if has_selection else None
            crop_button.setEnabled(has_selection)
            restore_button.setEnabled(
                bool(image and image.source_path and image.source_path.is_file())
            )

    def _selected_asset(self, role: str) -> tuple[int, StoredImage] | None:
        row = self._asset_list_for(role).currentRow()
        assets = self._assets_for(role)
        if not 0 <= row < len(assets):
            return None
        return row, assets[row]

    def _crop_selected(self, role: str) -> None:
        selected = self._selected_asset(role)
        if selected is None:
            return
        row, image = selected
        dialog = CropDialog(image.path, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        crop_box = dialog.crop_box()
        if crop_box is None:
            return
        try:
            candidate = self.file_store.save_cropped_reference(image, crop_box)
        except Exception as exc:
            QMessageBox.warning(self, "裁剪失败", str(exc))
            return
        self._replace_asset(role, row, candidate, action_label="裁剪")

    def _restore_selected(self, role: str) -> None:
        selected = self._selected_asset(role)
        if selected is None:
            return
        row, image = selected
        if not image.source_path or not image.source_path.is_file():
            QMessageBox.information(
                self,
                "无法恢复",
                "原始素材文件已不存在。",
            )
            self._update_asset_actions()
            return
        try:
            candidate = self.file_store.save_reference(image.source_path)
        except Exception as exc:
            QMessageBox.warning(self, "恢复失败", str(exc))
            return
        self._replace_asset(role, row, candidate, action_label="恢复")

    def _replace_asset(
        self,
        role: str,
        row: int,
        candidate: StoredImage,
        *,
        action_label: str,
    ) -> bool:
        assets = self._assets_for(role)
        if not 0 <= row < len(assets):
            return False
        if any(
            index != row and image.content_hash == candidate.content_hash
            for index, image in enumerate(assets)
        ):
            QMessageBox.information(
                self,
                "同列已有相同图片",
                f"该{ROLE_LABELS[role]}图片与当前列中的另一张图片内容相同，"
                "已取消替换。",
            )
            return False

        previous = assets[row]
        assets[row] = candidate
        if role == "garment" and self.selected_garment == previous:
            self.selected_garment = candidate
        self.pairs = [
            DressPair(
                garment=candidate if role == "garment" else pair.garment,
                person=candidate if role == "person" else pair.person,
            )
            if (
                (role == "garment" and pair.garment == previous)
                or (role == "person" and pair.person == previous)
            )
            else pair
            for pair in self.pairs
        ]
        self._refresh_role(role)
        self._asset_list_for(role).setCurrentRow(row)
        self._refresh_pairs()
        self.feedback_label.setText(
            f"{ROLE_LABELS[role]} {row + 1} 已{action_label}，相关配对已同步更新。"
        )
        return True

    def _append_assets(self, role: str, inputs: Sequence[Path]) -> None:
        assets = self._assets_for(role)
        remaining = MAX_BATCH_ASSETS - len(assets)
        if remaining <= 0:
            QMessageBox.information(
                self,
                "已达到上限",
                f"{ROLE_LABELS[role]}素材最多 {MAX_BATCH_ASSETS} 张。",
            )
            return

        paths, scan_errors = scan_image_inputs(inputs)
        known_hashes = {image.content_hash for image in assets}
        duplicate_count = 0
        invalid_messages = list(scan_errors)
        added = 0
        overflow = 0
        for index, path in enumerate(paths):
            if len(assets) >= MAX_BATCH_ASSETS:
                overflow = len(paths) - index
                break
            try:
                image = self.file_store.save_reference(path)
            except (OSError, ImageValidationError) as exc:
                invalid_messages.append(f"{path.name}：{exc}")
                continue
            if image.content_hash in known_hashes:
                duplicate_count += 1
                continue
            assets.append(image)
            known_hashes.add(image.content_hash)
            added += 1

        self._refresh_role(role)
        summary = [f"已添加 {added} 张{ROLE_LABELS[role]}图片"]
        if duplicate_count:
            summary.append(f"跳过 {duplicate_count} 张重复图片")
        if overflow:
            summary.append(f"因上限未导入 {overflow} 张")
        message = "，".join(summary) + "。"
        self.feedback_label.setText(message)
        if invalid_messages:
            QMessageBox.warning(
                self,
                "部分图片未导入",
                message + "\n\n" + "\n".join(invalid_messages[:8]),
            )
        elif duplicate_count or overflow:
            QMessageBox.information(self, "导入结果", message)

    def _add_image_files(self, role: str) -> None:
        remaining = MAX_BATCH_ASSETS - len(self._assets_for(role))
        if remaining <= 0:
            QMessageBox.information(
                self,
                "已达到上限",
                f"{ROLE_LABELS[role]}素材最多 {MAX_BATCH_ASSETS} 张。",
            )
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            f"选择{ROLE_LABELS[role]}图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;所有文件 (*)",
        )
        if paths:
            self._append_assets(role, [Path(path) for path in paths])

    def _add_image_folder(self, role: str) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            f"选择{ROLE_LABELS[role]}文件夹",
        )
        if directory:
            self._append_assets(role, [Path(directory)])

    def _add_library_images(self, role: str) -> None:
        remaining = MAX_BATCH_ASSETS - len(self._assets_for(role))
        if remaining <= 0:
            QMessageBox.information(
                self,
                "已达到上限",
                f"{ROLE_LABELS[role]}素材最多 {MAX_BATCH_ASSETS} 张。",
            )
            return
        dialog = LibraryPickerDialog(self.database, remaining, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._append_assets(role, dialog.selected_paths())

    def _remove_selected(self, role: str) -> None:
        asset_list = self._asset_list_for(role)
        row = asset_list.currentRow()
        assets = self._assets_for(role)
        if not 0 <= row < len(assets):
            return
        image = assets[row]
        related = self._pairs_for_image(role, image)
        if related and not self._confirm_pair_removal(
            f"该{ROLE_LABELS[role]}图已参与 {len(related)} 个配对，"
            "移除后将同时删除这些配对。"
        ):
            return
        assets.pop(row)
        self._remove_related_pairs(role, image)
        self._refresh_role(role)
        self._refresh_pairs()

    def _clear_role(self, role: str) -> None:
        assets = self._assets_for(role)
        if not assets:
            return
        related_count = sum(
            1
            for pair in self.pairs
            if (role == "garment" and pair.garment in assets)
            or (role == "person" and pair.person in assets)
        )
        if related_count and not self._confirm_pair_removal(
            f"清空后将同时删除 {related_count} 个相关配对。"
        ):
            return
        asset_hashes = {asset.content_hash for asset in assets}
        assets.clear()
        if role == "garment":
            self.pairs = [
                pair
                for pair in self.pairs
                if pair.garment.content_hash not in asset_hashes
            ]
            self.selected_garment = None
        else:
            self.pairs = [
                pair
                for pair in self.pairs
                if pair.person.content_hash not in asset_hashes
            ]
        self._refresh_role(role)
        self._refresh_pairs()

    def _confirm_pair_removal(self, detail: str) -> bool:
        answer = QMessageBox.question(
            self,
            "移除已配对素材",
            detail + "\n确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _pairs_for_image(self, role: str, image: StoredImage) -> list[DressPair]:
        if role == "garment":
            return [pair for pair in self.pairs if pair.garment == image]
        return [pair for pair in self.pairs if pair.person == image]

    def _remove_related_pairs(self, role: str, image: StoredImage) -> None:
        if role == "garment":
            self.pairs = [pair for pair in self.pairs if pair.garment != image]
        else:
            self.pairs = [pair for pair in self.pairs if pair.person != image]

    def _garment_selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        image = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.selected_garment = image if isinstance(image, StoredImage) else None
        self._update_asset_actions()
        if self.selected_garment:
            self.feedback_label.setText(
                f"已选择服装：{self.selected_garment.original_name}，请点击右侧人物图片。"
            )

    def _person_selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del current, previous
        self._update_asset_actions()

    def _person_clicked(self, item: QListWidgetItem) -> None:
        image = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(image, StoredImage):
            return
        if self.selected_garment is None:
            self.feedback_label.setText("请先点击一张服装图片，再点击人物图片。")
            return
        self._add_pair(self.selected_garment, image)

    def _garment_dropped(self, content_hash: str, person_row: int) -> None:
        garment = next(
            (
                image
                for image in self.garment_assets
                if image.content_hash == content_hash
            ),
            None,
        )
        if garment is None or not 0 <= person_row < len(self.person_assets):
            return
        self._add_pair(garment, self.person_assets[person_row])

    def _add_pair(self, garment: StoredImage, person: StoredImage) -> None:
        pair = DressPair(garment=garment, person=person)
        if any(existing.key == pair.key for existing in self.pairs):
            self.feedback_label.setText("这组“服装 × 人物”已经配对，无需重复添加。")
            self._reset_pair_selection()
            return
        self.pairs.append(pair)
        self.feedback_label.setText(
            f"已建立配对 {len(self.pairs)}："
            f"{garment.original_name} × {person.original_name}"
        )
        self._reset_pair_selection()
        self._refresh_pairs()

    def _reset_pair_selection(self) -> None:
        self.selected_garment = None
        self.garment_list.blockSignals(True)
        self.person_list.blockSignals(True)
        self.garment_list.clearSelection()
        self.person_list.clearSelection()
        self.garment_list.setCurrentRow(-1)
        self.person_list.setCurrentRow(-1)
        self.garment_list.blockSignals(False)
        self.person_list.blockSignals(False)
        self._update_asset_actions()

    def _remove_pair(self, pair: DressPair) -> None:
        self.pairs = [item for item in self.pairs if item.key != pair.key]
        self._refresh_pairs()

    def _clear_pairs(self) -> None:
        if not self.pairs:
            return
        self.pairs.clear()
        self._reset_pair_selection()
        self._refresh_pairs()
        self.feedback_label.setText("配对已清空，素材仍保留。")

    def _refresh_pairs(self) -> None:
        scrollbar = self.pair_scroll.verticalScrollBar()
        scroll_value = scrollbar.value()
        while self.pair_grid.count():
            item = self.pair_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.pair_count_label.setText(f"已建立 {len(self.pairs)} 个配对")
        for column in range(MAX_PAIR_COLUMNS):
            self.pair_grid.setColumnStretch(column, 0)
        if not self.pairs:
            empty = QLabel(
                "还没有配对。选择服装后点击人物，或把左侧服装缩略图拖到右侧人物上。"
            )
            empty.setWordWrap(True)
            empty.setStyleSheet("color:#7d8797;padding:24px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.pair_grid.addWidget(empty, 0, 0, 1, self.pair_columns)
            for column in range(self.pair_columns):
                self.pair_grid.setColumnStretch(column, 1)
            return
        for index, pair in enumerate(self.pairs):
            card = DressPairCard(pair, index + 1)
            card.remove_requested.connect(self._remove_pair)
            self.pair_grid.addWidget(
                card,
                index // self.pair_columns,
                index % self.pair_columns,
            )
        for column in range(self.pair_columns):
            self.pair_grid.setColumnStretch(column, 1)
        QTimer.singleShot(
            0,
            lambda: scrollbar.setValue(min(scroll_value, scrollbar.maximum())),
        )

    def _enqueue_all(self) -> None:
        if not self.secret_store.load():
            answer = QMessageBox.question(
                self,
                "尚未设置 API Key",
                "请先在设置中填写 API Key。现在打开设置吗？",
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.settings_requested.emit()
            return
        if not self.pairs:
            QMessageBox.information(self, "没有配对", "请至少建立一组服装与人物配对。")
            return
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.information(self, "缺少提示词", "请先填写换装提示词。")
            return

        count = self.count_spin.value()
        maximum = len(self.pairs) * count
        answer = QMessageBox.question(
            self,
            "确认批量生成",
            f"将创建 {len(self.pairs)} 个排队任务，每对最多生成 {count} 张，"
            f"本批最多 {maximum} 张图片。\n"
            "任务会串行执行并可能产生费用，失败后不会自动重试。\n"
            "确定加入队列吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        requests = [
            ImageRequest(
                model=self.model_combo.currentData(),
                prompt=prompt,
                n=count,
                aspect_ratio=self.aspect_combo.currentData(),
                resolution=self.resolution_combo.currentData(),
                reference_images=(pair.garment, pair.person),
                mode=MODE_DRESS_UP,
            )
            for pair in self.pairs
        ]
        try:
            task_ids = self.database.create_tasks(requests)
        except Exception as exc:
            QMessageBox.critical(self, "无法创建任务", str(exc))
            return

        self.pairs.clear()
        self._reset_pair_selection()
        self._refresh_pairs()
        self.worker.notify()
        self.tasks_enqueued.emit(len(task_ids))
        self.feedback_label.setText(
            f"已加入 {len(task_ids)} 个排队任务，"
            f"任务编号 #{task_ids[0]}–#{task_ids[-1]}。"
        )
        QMessageBox.information(
            self,
            "已加入队列",
            f"已加入 {len(task_ids)} 个任务。配对已清空，素材仍保留。\n"
            "可在“创作”的任务队列或“历史记录”中查看结果。",
        )

    def prepare_retry(self, task_id: int) -> None:
        task = self.database.get_task(task_id)
        if task is None or task["mode"] != MODE_DRESS_UP:
            return
        references = self.database.get_task_references(task_id)
        if len(references) != 2:
            return

        self.garment_assets = [references[0]]
        self.person_assets = [references[1]]
        self.pairs = [DressPair(references[0], references[1])]
        self.selected_garment = None
        self._refresh_role("garment")
        self._refresh_role("person")
        self._refresh_pairs()
        self.prompt_edit.setPlainText(task["prompt"])
        model_index = self.model_combo.findData(task["model"])
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)
        aspect_index = self.aspect_combo.findData(task["aspect_ratio"])
        if aspect_index >= 0:
            self.aspect_combo.setCurrentIndex(aspect_index)
        resolution_index = self.resolution_combo.findData(task["resolution"] or "auto")
        if resolution_index >= 0:
            self.resolution_combo.setCurrentIndex(resolution_index)
        self.count_spin.setValue(int(task["n"]))
        self.feedback_label.setText(
            f"已载入任务 #{task_id}，修改提示词或参数后重新生成。"
        )
        self.prompt_edit.setFocus()
