from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QApplication,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_NAME, STATUS_LABELS
from ..database import Database
from ..library import LibraryService
from ..logging_utils import register_sensitive_value
from ..paths import AppPaths
from ..security import SecretStore
from ..storage import FileStore
from ..worker import TaskWorker
from .create_page import CreatePage
from .dialogs import SettingsDialog
from .history_page import HistoryPage
from .library_page import LibraryPage


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        paths: AppPaths,
        database: Database,
        file_store: FileStore,
        library_service: LibraryService,
        secret_store: SecretStore,
        worker: TaskWorker,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.database = database
        self.secret_store = secret_store
        self.worker = worker
        self.setWindowIcon(QApplication.instance().windowIcon())
        self.setWindowTitle(APP_NAME)
        self.resize(1480, 920)
        self.setMinimumSize(1180, 720)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        self.create_page = CreatePage(
            database,
            file_store,
            library_service,
            worker,
            secret_store,
        )
        self.history_page = HistoryPage(database, library_service, worker)
        self.library_page = LibraryPage(database, library_service)
        self.stack.addWidget(self.create_page)
        self.stack.addWidget(self.history_page)
        self.stack.addWidget(self.library_page)
        root.addWidget(self.stack, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 12)
        content_layout.addWidget(self.stack)
        root.removeWidget(self.stack)
        root.addWidget(content, 1)
        self.setCentralWidget(central)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(
            f"数据目录：{self.paths.root} · 任务串行执行，生成请求不会自动重试"
        )

        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.create_page.settings_requested.connect(self.open_settings)
        self.create_page.library_changed.connect(self.library_page.refresh)
        self.history_page.library_changed.connect(self.library_page.refresh)
        self.history_page.retry_requested.connect(self._open_retry_in_create)
        self.worker.signals.task_changed.connect(self._on_task_changed)
        self.nav_list.setCurrentRow(0)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(210)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 24, 14, 18)
        layout.setSpacing(12)
        title = QLabel("亦欣 AI")
        title.setObjectName("BrandTitle")
        subtitle = QLabel("生图工作台 · Nano Banana")
        subtitle.setObjectName("BrandSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("NavList")
        for text in ("创作", "历史记录", "作品库"):
            item = QListWidgetItem(text)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            self.nav_list.addItem(item)
        layout.addWidget(self.nav_list)
        layout.addStretch(1)
        note = QLabel("未保存结果保留 7 天")
        note.setStyleSheet("color:#91a3bf;font-size:11px;")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        settings = QPushButton("设置")
        settings.setObjectName("GhostButton")
        settings.clicked.connect(self.open_settings)
        layout.addWidget(settings)
        return sidebar

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.secret_store, self.database, self)
        dialog.exec()
        register_sensitive_value(self.secret_store.load())

    def _on_task_changed(self, task_id: int, status: str) -> None:
        label = STATUS_LABELS.get(status, status)
        self.statusBar().showMessage(
            f"任务 #{task_id}：{label} · 数据目录：{self.paths.root}", 8000
        )

    def _open_retry_in_create(self, task_id: int) -> None:
        self.nav_list.setCurrentRow(0)
        self.create_page.prepare_retry(task_id)
        self.statusBar().showMessage(
            f"已载入任务 #{task_id}，修改参数后点击生成", 8000
        )

    def closeEvent(self, event) -> None:
        if self.database.has_running_tasks():
            answer = QMessageBox.warning(
                self,
                "仍有任务在执行",
                "关闭程序不会保证服务端停止当前请求，可能已经产生费用。\n"
                "确定强制退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.worker.shutdown()
        event.accept()
