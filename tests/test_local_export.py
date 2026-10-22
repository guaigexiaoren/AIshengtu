from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from yixin.database import Database
from yixin.local_export import LocalImageExporter
from yixin.models import ImageRequest
from yixin.paths import AppPaths
from yixin.settings import AppSettings
from yixin.storage import FileStore
from yixin.ui.save_helpers import LocalSaveController
from tests.helpers import make_image, png_bytes


class LocalExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = AppPaths(self.root / "data")
        self.paths.ensure()
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.store = FileStore(self.paths)
        self.settings = AppSettings(self.database)
        self.exporter = LocalImageExporter(self.database, self.settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _completed_task(self, prompt: str = "人物:海报?") -> tuple[int, int, Path]:
        source = make_image(self.root / "references" / "last.png", (10, 40, 90))
        reference = self.store.save_reference(source)
        task_id = self.database.create_task(
            ImageRequest(
                model="gemini-3-pro-image",
                prompt=prompt,
                n=1,
                aspect_ratio="3:4",
                resolution="2K",
                reference_images=(reference,),
                mode="reference",
            )
        )
        result_data = png_bytes((60, 100, 180), (80, 120))
        generated = self.store.store_generated(task_id, result_data, 0)
        thumbnail = self.store.create_thumbnail(generated.path)
        result_id = self.database.add_task_result(
            task_id, 0, generated, thumbnail_path=thumbnail, remote_url=None
        )
        return task_id, result_id, generated.path

    def test_preferred_directory_modes_and_fallback(self) -> None:
        task_id, _, _ = self._completed_task()
        fixed = self.root / "fixed"
        last = self.root / "last"
        fixed.mkdir()
        last.mkdir()

        self.settings.set_local_save_mode("fixed")
        self.settings.set_fixed_folder(fixed)
        self.assertEqual(self.exporter.preferred_directory(task_id), fixed)

        self.settings.set_local_save_mode("reference")
        self.assertEqual(
            self.exporter.preferred_directory(task_id),
            self.root / "references",
        )

        with self.database.connection() as connection:
            connection.execute("UPDATE task_assets SET source_path = NULL")
        self.settings.set_last_folder(last)
        self.assertEqual(self.exporter.preferred_directory(task_id), last)

    def test_local_save_copies_only_result_and_avoids_overwrite(self) -> None:
        task_id, result_id, result_path = self._completed_task()
        destination = self.root / "exports"
        destination.mkdir()
        first = self.exporter.save_result(task_id, result_id, destination)
        second = self.exporter.save_result(task_id, result_id, destination)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), Path(result_path).read_bytes())
        self.assertEqual(len(list(destination.iterdir())), 2)
        self.assertNotIn(":", first.name)
        self.assertNotIn("?", first.name)
        self.assertRegex(second.stem, r"_2$")
        self.assertEqual(self.settings.last_folder(), destination.resolve())

    def test_ask_mode_chooses_folder_and_updates_last_folder(self) -> None:
        task_id, result_id, _ = self._completed_task()
        destination = self.root / "ask-export"
        destination.mkdir()
        controller = LocalSaveController(QWidget(), self.exporter, self.settings)
        with patch(
            "yixin.ui.save_helpers.QFileDialog.getExistingDirectory",
            return_value=str(destination),
        ):
            saved = controller.save(task_id, result_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.parent, destination.resolve())
        self.assertEqual(self.settings.last_folder(), destination.resolve())

    def test_invalid_fixed_folder_prompts_and_updates_setting(self) -> None:
        task_id, result_id, _ = self._completed_task()
        self.settings.set_local_save_mode("fixed")
        self.settings.set_fixed_folder(self.root / "missing")
        destination = self.root / "replacement"
        destination.mkdir()
        controller = LocalSaveController(QWidget(), self.exporter, self.settings)
        with (
            patch(
                "yixin.ui.save_helpers.QFileDialog.getExistingDirectory",
                return_value=str(destination),
            ),
            patch("yixin.ui.save_helpers.QMessageBox.information"),
        ):
            saved = controller.save(task_id, result_id)
        self.assertIsNotNone(saved)
        self.assertEqual(self.settings.fixed_folder(), destination.resolve())


if __name__ == "__main__":
    unittest.main()
