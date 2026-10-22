from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from yixin.constants import TASK_CANCELLED, TASK_FAILED, TASK_SUCCESS
from yixin.database import Database
from yixin.models import ApiError, ImageApiResult, ImageRequest, RemoteImage
from yixin.paths import AppPaths
from yixin.storage import FileStore
from yixin.worker import TaskWorker
from tests.helpers import png_bytes


class FakeClient:
    def __init__(self, *, failure: ApiError | None = None) -> None:
        self.failure = failure
        self.image_bytes = png_bytes((30, 90, 160))
        self.calls = 0

    def generate(self, request: ImageRequest) -> ImageApiResult:
        self.calls += 1
        if self.failure:
            raise self.failure
        return ImageApiResult(
            images=(
                RemoteImage(
                    b64_json=base64.b64encode(self.image_bytes).decode("ascii")
                ),
            ),
            request_id="mock-request",
            remote_task_id="mock-task",
            usage_input_tokens=7,
            usage_output_tokens=9,
            raw_response={"data": [{"b64_json": "[图片数据已省略]"}]},
            status_code=200,
        )

    def resolve_image(self, image: RemoteImage) -> bytes:
        return self.image_bytes


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temp.name) / "data")
        self.paths.ensure()
        self.database = Database(self.paths.database)
        self.database.initialize()
        self.store = FileStore(self.paths)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _request(self) -> ImageRequest:
        return ImageRequest(
            model="gemini-3-pro-image",
            prompt="队列测试",
            n=1,
            aspect_ratio="3:4",
            resolution="2K",
            mode="text",
        )

    def test_process_task_success(self) -> None:
        task_id = self.database.create_task(self._request())
        claimed = self.database.claim_next_queued()
        fake = FakeClient()
        worker = TaskWorker(self.database, fake, self.store)
        worker.process_task(claimed)
        task = self.database.get_task(task_id)
        self.assertEqual(task["status"], TASK_SUCCESS)
        self.assertEqual(task["request_id"], "mock-request")
        self.assertEqual(task["remote_task_id"], "mock-task")
        results = self.database.get_task_results(task_id)
        self.assertEqual(len(results), 1)
        self.assertTrue(Path(results[0]["path"]).is_file())
        self.assertTrue(Path(results[0]["thumbnail_path"]).is_file())
        self.assertEqual(task["input_tokens"], 7)
        self.assertEqual(task["output_tokens"], 9)

    def test_cancel_running_does_not_store_result(self) -> None:
        task_id = self.database.create_task(self._request())
        claimed = self.database.claim_next_queued()
        fake = FakeClient()
        worker = TaskWorker(self.database, fake, self.store)
        class CancelAfterGenerateClient(FakeClient):
            def generate(inner_self, request):
                result = super().generate(request)
                self.database.request_cancel(task_id)
                return result

        worker.client = CancelAfterGenerateClient()
        worker.process_task(claimed)
        task = self.database.get_task(task_id)
        self.assertEqual(task["status"], TASK_CANCELLED)
        self.assertEqual(self.database.get_task_results(task_id), [])
        self.assertEqual(fake.calls, 0)

    def test_api_failure_records_request_id(self) -> None:
        task_id = self.database.create_task(self._request())
        claimed = self.database.claim_next_queued()
        fake = FakeClient(
            failure=ApiError(
                "测试失败",
                status_code=500,
                request_id="req-failure",
                error_code="http_500",
            )
        )
        worker = TaskWorker(self.database, fake, self.store)
        worker.process_task(claimed)
        task = self.database.get_task(task_id)
        self.assertEqual(task["status"], TASK_FAILED)
        self.assertEqual(task["request_id"], "req-failure")
        self.assertEqual(task["error_code"], "http_500")


if __name__ == "__main__":
    unittest.main()
