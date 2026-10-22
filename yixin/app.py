from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .api import NanoBananaClient
from .constants import APP_NAME, APP_ORGANIZATION, TEMP_RETENTION_DAYS
from .database import Database
from .library import LibraryService
from .logging_utils import register_sensitive_value, setup_logging
from .paths import AppPaths, resource_path
from .security import SecretStore
from .storage import FileStore
from .ui.main_window import MainWindow
from .ui.theme import APP_STYLESHEET
from .worker import TaskWorker


def run() -> int:
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Yixin.AIImageWorkbench.1"
            )
        except Exception:
            pass
    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORGANIZATION)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(APP_STYLESHEET)
    app.setWindowIcon(QIcon(str(resource_path("assets", "app_icon.ico"))))
    translator = QTranslator(app)
    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qt_zh_CN", translations_path):
        app.installTranslator(translator)
        app.translator = translator

    paths = AppPaths.default()
    try:
        paths.ensure()
        logger = setup_logging(paths.log_file)
        logger.info("应用启动，数据目录：%s", paths.root)
        database = Database(paths.database)
        database.initialize()
        cancelled = database.recover_after_restart()
        if cancelled:
            logger.info("已将 %s 个用户停止等待的任务恢复为已取消", cancelled)
        file_store = FileStore(paths)
        file_store.cleanup_temp(
            database.active_temp_paths(),
            days=TEMP_RETENTION_DAYS,
        )
        secret_store = SecretStore(paths.api_key_file)
        register_sensitive_value(secret_store.load())
        client = NanoBananaClient(lambda: secret_store.load())
        worker = TaskWorker(database, client, file_store)
        library_service = LibraryService(database, file_store, paths)
        window = MainWindow(
            paths=paths,
            database=database,
            file_store=file_store,
            library_service=library_service,
            secret_store=secret_store,
            worker=worker,
        )
    except Exception as exc:
        QMessageBox.critical(None, "启动失败", f"程序无法启动：\n{exc}")
        return 1

    def cleanup_temp() -> None:
        try:
            file_store.cleanup_temp(
                database.active_temp_paths(),
                days=TEMP_RETENTION_DAYS,
            )
        except Exception:
            logger.exception("自动清理临时文件失败")

    cleanup_timer = QTimer(window)
    cleanup_timer.setInterval(24 * 60 * 60 * 1000)
    cleanup_timer.timeout.connect(cleanup_temp)
    cleanup_timer.start()
    app.aboutToQuit.connect(worker.shutdown)

    window.show()
    worker.start()
    exit_code = app.exec()
    logger.info("应用退出")
    return exit_code
