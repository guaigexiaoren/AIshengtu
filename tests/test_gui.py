from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from yixin.database import Database
from yixin.library import LibraryService
from yixin.models import ImageApiResult, ImageRequest, RemoteImage
from yixin.paths import AppPaths
from yixin.security import SecretStore
from yixin.settings import AppSettings
from yixin.storage import FileStore
from yixin.ui.dialogs import LibraryPickerDialog
from yixin.ui.crop import CropCanvas
from yixin.ui.main_window import MainWindow
from yixin.ui.theme import APP_STYLESHEET
from yixin.ui.widgets import (
    ReferenceDropGroup,
    ReorderableImageStrip,
    load_scaled_pixmap,
    local_image_paths,
)
from yixin.worker import TaskWorker
from tests.helpers import make_image, png_bytes


class FakeGuiClient:
    def __init__(self) -> None:
        self.image_bytes = png_bytes((60, 50, 160), (75, 100))

    def generate(self, request: ImageRequest) -> ImageApiResult:
        encoded = base64.b64encode(self.image_bytes).decode("ascii")
        return ImageApiResult(
            images=tuple(
                RemoteImage(b64_json=encoded) for _ in range(request.n)
            ),
            request_id="gui-request",
            remote_task_id="gui-task",
            usage_input_tokens=3,
            usage_output_tokens=5,
            raw_response={"data": [{"b64_json": "[图片数据已省略]"}]},
            status_code=200,
        )

    def resolve_image(self, image: RemoteImage) -> bytes:
        return self.image_bytes


class GuiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(APP_STYLESHEET)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temp.name) / "data with space")
        self.paths.ensure()
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.store = FileStore(self.paths)
        self.secret_store = SecretStore(self.paths.api_key_file)
        self.secret_store.save("sk-gui-test-123456")
        fake_client = FakeGuiClient()
        self.worker = TaskWorker(self.database, fake_client, self.store)
        self.library = LibraryService(self.database, self.store, self.paths)
        self.window = MainWindow(
            paths=self.paths,
            database=self.database,
            file_store=self.store,
            library_service=self.library,
            secret_store=self.secret_store,
            worker=self.worker,
        )
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_defaults_model_and_reference_limit(self) -> None:
        page = self.window.create_page
        self.assertEqual(page.aspect_combo.currentData(), "3:4")
        self.assertEqual(page.resolution_combo.currentData(), "2K")
        self.assertEqual(page.model_combo.currentData(), "gemini-3-pro-image")
        self.assertEqual(page.mode_combo.currentData(), "reference")
        self.assertTrue(page.reference_group.isVisible())
        self.assertIn("14", page.reference_count_label.text())

    def test_full_gui_task_save_and_reopen(self) -> None:
        page = self.window.create_page
        source = make_image(Path(self.temp.name) / "reference.png")
        page.mode_combo.setCurrentIndex(1)
        page._add_stored_references([source])
        self.assertEqual(len(page.reference_images), 1)
        page.prompt_edit.setPlainText("将参考图改成春天的户外人像")
        page._enqueue_generation()
        self.assertIsNotNone(page.current_task_id)
        self.assertEqual(page.queue_table.rowCount(), 1)
        task = self.database.claim_next_queued()
        self.worker.process_task(task)
        self.app.processEvents()
        results = self.database.get_task_results(task["id"])
        self.assertEqual(len(results), 1)
        work_id = self.library.save_task_result(task["id"], results[0]["id"])
        self.window.library_page.refresh()
        self.app.processEvents()
        self.assertEqual(self.window.library_page.work_list.count(), 1)
        self.assertIsNotNone(self.database.get_work(work_id))
        folder = self.library.work_folder(work_id)
        self.assertTrue(folder.is_dir())
        self.assertTrue(any(folder.glob("output.*")))
        self.assertTrue((folder / "reference_01.png").is_file())
        self.assertTrue((folder / "thumbnail.jpg").is_file())
        self.window.library_page.show_work(work_id)
        self.assertTrue(self.window.library_page.current_assets)
        self.assertEqual(self.window.library_page.path_edit.text(), str(folder))
        with patch.object(self.database, "get_work_assets") as get_assets:
            picker = LibraryPickerDialog(self.database, 14, self.window)
        self.assertFalse(get_assets.called)
        self.assertEqual(picker.list_widget.count(), 1)
        picker.close()
        with patch(
            "yixin.ui.library_page.QDesktopServices.openUrl", return_value=True
        ) as open_url:
            self.window.library_page._open_work_folder()
        opened_url = open_url.call_args.args[0]
        self.assertEqual(Path(opened_url.toLocalFile()), folder)

    def test_template_can_be_applied(self) -> None:
        self.database.save_template("测试模板", "来自模板的提示词")
        page = self.window.create_page
        page.refresh_templates()
        for index in range(page.template_combo.count()):
            data = page.template_combo.itemData(index)
            if data and data["name"] == "测试模板":
                page.template_combo.setCurrentIndex(index)
                break
        page._apply_template()
        self.assertEqual(page.prompt_edit.toPlainText(), "来自模板的提示词")

    def test_ui_reference_limit_is_fourteen(self) -> None:
        page = self.window.create_page
        page.mode_combo.setCurrentIndex(1)
        source = make_image(Path(self.temp.name) / "limit.png")
        with patch("yixin.ui.create_page.QMessageBox.information"):
            page._add_stored_references([source] * 15)
            page._add_stored_references([source])
        self.assertEqual(len(page.reference_images), 14)
        self.assertIn("14 / 14", page.reference_count_label.text())

    def test_queue_is_below_generate_and_inside_scroll_content(self) -> None:
        page = self.window.create_page
        self.assertIs(page.queue_group.parent(), page.form_content)
        self.app.processEvents()
        generate_bottom = page.generate_button.mapTo(
            page.form_content, QPoint(0, page.generate_button.height())
        ).y()
        queue_top = page.queue_group.mapTo(page.form_content, QPoint(0, 0)).y()
        self.assertGreater(queue_top, generate_bottom)
        self.assertLess(queue_top - generate_bottom, 180)

    def test_mixed_reference_and_result_preview_in_create_and_history(self) -> None:
        page = self.window.create_page
        first = make_image(Path(self.temp.name) / "ref1.png", (10, 30, 90))
        second = make_image(Path(self.temp.name) / "ref2.png", (90, 30, 10))
        page.mode_combo.setCurrentIndex(1)
        page._add_stored_references([first, second])
        page.prompt_edit.setPlainText("组合两张参考图并生成两版结果")
        page.count_spin.setValue(2)
        page._enqueue_generation()
        task = self.database.claim_next_queued()
        self.worker.process_task(task)
        self.app.processEvents()

        labels = [
            page.asset_strip.item(index).text()
            for index in range(page.asset_strip.count())
        ]
        self.assertEqual(labels, ["参考 1", "参考 2", "结果 1", "结果 2"])
        self.assertEqual(page.asset_strip.currentRow(), 2)
        first_result = page.current_results[0]
        self.assertEqual(Path(page.preview.current_path), Path(first_result["path"]))
        self.assertTrue(page.save_local_button.isEnabled())
        self.assertTrue(page.save_library_button.isEnabled())
        self.assertTrue(page.compare_button.isEnabled())

        page.asset_strip.setCurrentRow(0)
        self.app.processEvents()
        reference_path = page.reference_images[0].path
        self.assertEqual(Path(page.preview.current_path), Path(reference_path))
        self.assertFalse(page.save_local_button.isEnabled())
        self.assertFalse(page.save_library_button.isEnabled())

        page.reference_strip.setCurrentRow(1)
        self.app.processEvents()
        second_reference_path = page.reference_images[1].path
        self.assertEqual(Path(page.preview.current_path), Path(second_reference_path))
        self.assertEqual(page.asset_strip.currentRow(), 1)
        with patch("yixin.ui.create_page.CompareDialog") as compare_dialog:
            page._compare_reference()
        self.assertEqual(
            Path(compare_dialog.call_args.args[0]), Path(second_reference_path)
        )
        self.assertEqual(
            Path(compare_dialog.call_args.args[1]),
            Path(page.current_results[0]["path"]),
        )
        page.asset_strip.setCurrentRow(3)
        with patch("yixin.ui.create_page.CompareDialog") as compare_dialog:
            page._compare_reference()
        self.assertEqual(
            Path(compare_dialog.call_args.args[0]),
            Path(page.reference_images[0].path),
        )
        self.assertEqual(
            Path(compare_dialog.call_args.args[1]),
            Path(page.current_results[1]["path"]),
        )

        history = self.window.history_page
        history.show_task(task["id"])
        history_labels = [
            history.asset_strip.item(index).text()
            for index in range(history.asset_strip.count())
        ]
        self.assertEqual(history_labels, labels)
        history.asset_strip.setCurrentRow(0)
        self.assertFalse(history.save_local_button.isEnabled())
        self.assertFalse(history.save_library_button.isEnabled())
        history.asset_strip.setCurrentRow(2)
        self.assertTrue(history.save_local_button.isEnabled())
        self.assertTrue(history.save_library_button.isEnabled())

    def test_reference_drop_filters_supported_local_images(self) -> None:
        valid = make_image(Path(self.temp.name) / "drop.png")
        invalid = Path(self.temp.name) / "ignore.txt"
        invalid.write_text("not image", encoding="utf-8")
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(valid)), QUrl.fromLocalFile(str(invalid))])
        received: list[Path] = []
        group = ReferenceDropGroup("拖放测试")
        group.files_dropped.connect(received.extend)
        event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        group.dropEvent(event)
        self.assertEqual(received, [valid])
        self.assertEqual(local_image_paths(mime.urls()), [valid])

        list_received: list[Path] = []
        strip = ReorderableImageStrip()
        strip.files_dropped.connect(list_received.extend)
        list_mime = QMimeData()
        list_mime.setUrls([QUrl.fromLocalFile(str(valid))])
        list_event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            list_mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        strip.dropEvent(list_event)
        self.assertEqual(list_received, [valid])

    def test_scaled_pixmap_never_exceeds_requested_size(self) -> None:
        source = make_image(
            Path(self.temp.name) / "large-preview.png",
            (20, 40, 80),
        )
        pixmap = load_scaled_pixmap(source, QSize(64, 48))
        self.assertFalse(pixmap.isNull())
        self.assertLessEqual(pixmap.width(), 64)
        self.assertLessEqual(pixmap.height(), 48)

    def test_clicking_task_loads_the_complete_generation_form(self) -> None:
        reference = self.store.save_reference(
            make_image(Path(self.temp.name) / "task-param.png")
        )
        task_id = self.database.create_task(
            ImageRequest(
                model="gemini-nano-banana-2.1",
                prompt="从任务列表恢复的参数",
                n=3,
                aspect_ratio="16:9",
                resolution="4K",
                reference_images=(reference,),
                mode="reference",
            )
        )
        page = self.window.create_page
        page.refresh_queue()
        page.queue_table.selectRow(0)
        self.app.processEvents()
        self.assertEqual(page.current_task_id, task_id)
        self.assertEqual(page.model_combo.currentData(), "gemini-nano-banana-2.1")
        self.assertEqual(page.mode_combo.currentData(), "reference")
        self.assertEqual(page.prompt_edit.toPlainText(), "从任务列表恢复的参数")
        self.assertEqual(page.aspect_combo.currentData(), "16:9")
        self.assertEqual(page.resolution_combo.currentData(), "4K")
        self.assertEqual(page.count_spin.value(), 3)
        self.assertEqual(len(page.reference_images), 1)

    def test_successful_task_retry_opens_editable_create_form(self) -> None:
        task_id = self.database.create_task(
            ImageRequest(
                model="gemini-3-pro-image",
                prompt="原始提示词",
                n=1,
                aspect_ratio="3:4",
                resolution="2K",
                mode="text",
            )
        )
        claimed = self.database.claim_next_queued()
        self.worker.process_task(claimed)
        self.app.processEvents()
        history = self.window.history_page
        history.show_task(task_id)
        self.assertEqual(history.cancel_button.text(), "取消任务")
        self.assertTrue(history.retry_button.isEnabled())
        history._retry_current()
        self.app.processEvents()
        self.assertEqual(self.window.nav_list.currentRow(), 0)
        self.assertEqual(len(self.database.list_tasks()), 1)
        page = self.window.create_page
        self.assertEqual(page.current_task_id, task_id)
        self.assertEqual(page.mode_combo.currentData(), "text")
        self.assertEqual(page.prompt_edit.toPlainText(), "原始提示词")
        self.assertIn("修改参数后重新生成", page.task_status_label.text())

        page.model_combo.setCurrentIndex(
            page.model_combo.findData("gemini-nano-banana-2.1")
        )
        page.prompt_edit.setPlainText("修改后的新提示词")
        page._enqueue_generation()
        tasks = self.database.list_tasks()
        self.assertEqual(len(tasks), 2)
        self.assertNotEqual(page.current_task_id, task_id)
        self.assertEqual(tasks[0]["status"], "queued")
        self.assertEqual(tasks[0]["model"], "gemini-nano-banana-2.1")
        self.assertEqual(tasks[0]["prompt"], "修改后的新提示词")
        self.assertEqual(self.database.get_task(task_id)["prompt"], "原始提示词")

    def test_library_no_longer_shows_favorite_or_compare(self) -> None:
        page = self.window.library_page
        self.assertFalse(hasattr(page, "favorite_check"))
        self.assertFalse(hasattr(page, "favorite_button"))
        self.assertFalse(hasattr(page, "compare_button"))
        self.assertEqual(
            page.work_list.selectionMode(),
            page.work_list.SelectionMode.SingleSelection,
        )

    def test_local_save_buttons_export_selected_result(self) -> None:
        page = self.window.create_page
        page.mode_combo.setCurrentIndex(1)
        page._add_stored_references(
            [make_image(Path(self.temp.name) / "save-reference.png")]
        )
        page.prompt_edit.setPlainText("本地保存按钮测试")
        page._enqueue_generation()
        claimed = self.database.claim_next_queued()
        self.worker.process_task(claimed)
        self.app.processEvents()
        page.asset_strip.setCurrentRow(1)
        settings = AppSettings(self.database)
        export_dir = Path(self.temp.name) / "button-export"
        export_dir.mkdir()
        settings.set_local_save_mode("fixed")
        settings.set_fixed_folder(export_dir)
        with patch("yixin.ui.create_page.show_saved_path") as saved_dialog:
            page._save_local_result()
        self.assertEqual(saved_dialog.call_count, 1)
        self.assertEqual(len(list(export_dir.iterdir())), 1)

    def test_reference_reorder_updates_next_task_but_not_submitted_task(self) -> None:
        page = self.window.create_page
        first = make_image(Path(self.temp.name) / "order-a.png", (10, 30, 90))
        second = make_image(Path(self.temp.name) / "order-b.png", (90, 30, 10))
        page._add_stored_references([first, second])
        self.assertFalse(page.reference_strip.dragEnabled())
        original_hashes = [image.content_hash for image in page.reference_images]
        page.reference_strip.move_item(0, 1)
        self.assertEqual(
            [image.content_hash for image in page.reference_images],
            list(reversed(original_hashes)),
        )
        self.assertEqual(page.reference_strip.item(0).text(), "参考 1")
        page.prompt_edit.setPlainText("排序后的新任务")
        page._enqueue_generation()
        task_id = page.current_task_id
        self.assertIsNotNone(task_id)
        saved_order = [
            image.content_hash
            for image in self.database.get_task_references(task_id)
        ]
        self.assertEqual(saved_order, list(reversed(original_hashes)))

        before = saved_order
        page.load_task_into_form(task_id)
        page.reference_strip.move_item(0, 1)
        after = [
            image.content_hash
            for image in self.database.get_task_references(task_id)
        ]
        self.assertEqual(after, before)
        self.assertIn("仅用于下一次生成", page.task_status_label.text())

    def test_reference_drop_insert_positions_are_exact(self) -> None:
        first = make_image(Path(self.temp.name) / "drop-a.png", (10, 30, 90))
        second = make_image(Path(self.temp.name) / "drop-b.png", (40, 80, 120))
        third = make_image(Path(self.temp.name) / "drop-c.png", (150, 80, 20))
        strip = ReorderableImageStrip(icon_size=48)
        strip.resize(360, 130)
        strip.show()
        self.app.processEvents()

        def reset_items() -> None:
            strip.set_images(
                [(first, "A", "A"), (second, "B", "B"), (third, "C", "C")]
            )
            self.app.processEvents()

        def drag(source_row: int, position: QPointF) -> list[str]:
            start = strip.visualItemRect(strip.item(source_row)).center()
            QTest.mousePress(
                strip.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                start,
            )
            for fraction in (0.25, 0.5, 0.75, 1.0):
                target = position.toPoint()
                point = QPoint(
                    round(start.x() + (target.x() - start.x()) * fraction),
                    round(start.y() + (target.y() - start.y()) * fraction),
                )
                QTest.mouseMove(strip.viewport(), point, 30)
            QTest.mouseRelease(
                strip.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                position.toPoint(),
            )
            self.app.processEvents()
            return [strip.item(i).text() for i in range(strip.count())]

        reset_items()
        first_rect = strip.visualItemRect(strip.item(0))
        self.assertEqual(
            drag(2, QPointF(first_rect.left() + 1, first_rect.center().y())),
            ["C", "A", "B"],
        )
        reset_items()
        first_rect = strip.visualItemRect(strip.item(0))
        second_rect = strip.visualItemRect(strip.item(1))
        self.assertEqual(
            drag(
                2,
                QPointF(
                    (first_rect.right() + second_rect.left()) / 2,
                    first_rect.center().y(),
                ),
            ),
            ["A", "C", "B"],
        )
        reset_items()
        third_rect = strip.visualItemRect(strip.item(2))
        self.assertEqual(
            drag(1, QPointF(third_rect.right() + 8, third_rect.center().y())),
            ["A", "C", "B"],
        )
        strip.close()

    def test_crop_and_restore_selected_reference_draft(self) -> None:
        page = self.window.create_page
        source = make_image(Path(self.temp.name) / "crop-source.png")
        page._add_stored_references([source])
        original = page.reference_images[0]
        page.reference_strip.setCurrentRow(0)

        class FakeCropDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, *args, **kwargs) -> None:
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def crop_box(self):
                return (10, 10, 50, 50)

        with patch("yixin.ui.create_page.CropDialog", FakeCropDialog):
            page._crop_selected_reference()
        cropped = page.reference_images[0]
        self.assertNotEqual(cropped.content_hash, original.content_hash)
        self.assertEqual((cropped.width, cropped.height), (40, 40))
        self.assertEqual(cropped.source_path, source.resolve())
        self.assertEqual(page.reference_strip.currentRow(), 0)

        page._restore_selected_reference()
        restored = page.reference_images[0]
        self.assertEqual(restored.content_hash, original.content_hash)
        self.assertEqual((restored.width, restored.height), (64, 80))

    def test_total_elapsed_is_shown_in_create_and_history(self) -> None:
        task_id = self.database.create_task(
            ImageRequest(
                model="gemini-3-pro-image",
                prompt="耗时显示",
                n=1,
                aspect_ratio="3:4",
                resolution="2K",
                mode="text",
            )
        )
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET status = 'success',
                    created_at = '2026-01-01T10:00:00+00:00',
                    finished_at = '2026-01-01T10:05:12+00:00'
                WHERE id = ?
                """,
                (task_id,),
            )
        page = self.window.create_page
        page.refresh_queue()
        self.assertEqual(page.queue_table.item(0, 2).text(), "5分12秒")
        page.show_task(task_id)
        self.assertIn("5分12秒", page.elapsed_label.text())

        history = self.window.history_page
        history.refresh()
        history.show_task(task_id)
        self.assertIn("5分12秒", history.elapsed_label.text())
        row = history._find_task_row(task_id)
        self.assertEqual(history.table.item(row, 3).text(), "5分12秒")

    def test_crop_canvas_returns_pixel_box(self) -> None:
        source = make_image(Path(self.temp.name) / "canvas-crop.png")
        canvas = CropCanvas(source)
        canvas._crop.setRect(0.25, 0.25, 0.5, 0.5)
        self.assertEqual(canvas.crop_box(), (16, 20, 48, 60))


if __name__ == "__main__":
    unittest.main()
