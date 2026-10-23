from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

import httpx

from yixin.api import NanoBananaClient
from yixin.constants import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    MODE_DRESS_UP,
    MODE_FREE_COMPOSE,
)
from yixin.models import ApiError, ImageRequest, StoredImage
from yixin.storage import FileStore, data_url_for_file
from yixin.paths import AppPaths
from tests.helpers import png_bytes


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temp.name) / "data")
        self.paths.ensure()
        self.store = FileStore(self.paths)
        self.reference = self.store.save_reference(
            self._write_source("reference.png", (20, 80, 140))
        )
        self.second_reference = self.store.save_reference(
            self._write_source("reference2.png", (140, 80, 20))
        )
        self.key = "sk-test-1234567890"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_source(self, name: str, color: tuple[int, int, int]) -> Path:
        path = Path(self.temp.name) / name
        path.write_bytes(png_bytes(color))
        return path

    def _request(
        self,
        *,
        refs: tuple[StoredImage, ...] = (),
        model: str = "gemini-3-pro-image",
        resolution: str | None = DEFAULT_RESOLUTION,
    ) -> ImageRequest:
        return ImageRequest(
            model=model,
            prompt="测试画面",
            n=1,
            aspect_ratio=DEFAULT_ASPECT_RATIO,
            resolution=resolution,
            reference_images=refs,
            mode="reference" if refs else "text",
        )

    def test_default_payload_has_only_nano_banana_fields(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        payload = client.build_payload(self._request())
        self.assertEqual(payload["model"], "gemini-3-pro-image")
        self.assertEqual(payload["prompt"], "测试画面")
        self.assertEqual(payload["aspect_ratio"], "3:4")
        self.assertEqual(payload["resolution"], "2K")
        self.assertEqual(set(payload), {"model", "prompt", "n", "aspect_ratio", "resolution"})
        for forbidden in ("mask", "quality", "background", "moderation", "format", "image", "images"):
            self.assertNotIn(forbidden, payload)

    def test_auto_resolution_is_omitted(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        payload = client.build_payload(self._request(resolution="auto"))
        self.assertNotIn("resolution", payload)

    def test_all_nano_banana_models_are_supported(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        for model in (
            "gemini-nano-banana-2.1",
            "gemini-3.1-flash-image",
            "gemini-3-pro-image",
        ):
            payload = client.build_payload(self._request(model=model))
            self.assertEqual(payload["model"], model)

    def test_one_reference_uses_image(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        payload = client.build_payload(self._request(refs=(self.reference,)))
        self.assertTrue(payload["image"].startswith("data:image/png;base64,"))
        self.assertNotIn("images", payload)
        self.assertNotIn("mask", payload)

    def test_multiple_references_use_images_in_order(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        request = ImageRequest(
            model="gemini-3-pro-image",
            prompt="组合两张参考图",
            n=2,
            aspect_ratio="3:4",
            resolution="2K",
            reference_images=(self.reference, self.second_reference),
            mode="reference",
        )
        payload = client.build_payload(request)
        self.assertEqual(len(payload["images"]), 2)
        self.assertNotIn("image", payload)
        self.assertNotEqual(payload["images"][0], payload["images"][1])

    def test_batch_dress_up_mode_is_not_sent_and_keeps_reference_order(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        request = ImageRequest(
            model="gemini-3-pro-image",
            prompt="将第1张服装穿到第2张人物身上",
            n=1,
            aspect_ratio="3:4",
            resolution="2K",
            reference_images=(self.reference, self.second_reference),
            mode="dress_up",
        )
        payload = client.build_payload(request)
        self.assertNotIn("mode", payload)
        self.assertEqual(len(payload["images"]), 2)
        self.assertEqual(
            payload["images"][0],
            data_url_for_file(self.reference.path, self.reference.mime),
        )
        self.assertEqual(
            payload["images"][1],
            data_url_for_file(self.second_reference.path, self.second_reference.mime),
        )

    def test_multi_reference_dress_up_and_free_compose_modes(self) -> None:
        client = NanoBananaClient(lambda: self.key)
        dress_up = ImageRequest(
            model="gemini-3-pro-image",
            prompt="自动匹配：第 1 至第 2 张为服装参考，第 3 张为人物参考。",
            reference_images=(
                self.reference,
                self.second_reference,
                self.reference,
            ),
            mode=MODE_DRESS_UP,
        )
        payload = client.build_payload(dress_up)
        self.assertEqual(len(payload["images"]), 3)
        self.assertNotIn("mode", payload)

        free_compose = ImageRequest(
            model="gemini-3-pro-image",
            prompt="自由组合：第 1 张为人物素材。",
            reference_images=(self.reference,),
            mode=MODE_FREE_COMPOSE,
        )
        payload = client.build_payload(free_compose)
        self.assertTrue(payload["image"].startswith("data:image/png;base64,"))
        self.assertNotIn("images", payload)
        self.assertNotIn("mode", payload)

    def test_fifteen_references_are_rejected(self) -> None:
        refs = tuple(self.reference for _ in range(15))
        request = ImageRequest(
            model="gemini-3-pro-image",
            prompt="太多参考图",
            n=1,
            aspect_ratio="3:4",
            resolution="2K",
            reference_images=refs,
            mode="reference",
        )
        with self.assertRaisesRegex(ValueError, "14"):
            request.validate()

    def test_url_response_download_without_authorization(self) -> None:
        captured: dict[str, object] = {}
        image_data = png_bytes((10, 120, 80))

        def post_handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["auth"] = request.headers.get("authorization")
            self.assertIn(b'"aspect_ratio":"3:4"', request.content)
            self.assertIn(b'"model":"gemini-3-pro-image"', request.content)
            return httpx.Response(
                200,
                json={
                    "data": [{"url": "https://files.example/result.png"}],
                    "usage": {"input_tokens": 12, "output_tokens": 34},
                },
                headers={"X-Request-Id": "req-url-1"},
            )

        def get_handler(request: httpx.Request) -> httpx.Response:
            captured["download_auth"] = request.headers.get("authorization")
            return httpx.Response(200, content=image_data)

        client = NanoBananaClient(
            lambda: self.key,
            transport=httpx.MockTransport(post_handler),
            download_transport=httpx.MockTransport(get_handler),
        )
        result = client.generate(self._request())
        self.assertEqual(captured["path"], "/v1/images/generations")
        self.assertEqual(captured["auth"], f"Bearer {self.key}")
        self.assertEqual(result.request_id, "req-url-1")
        self.assertEqual(result.usage_input_tokens, 12)
        self.assertEqual(result.usage_output_tokens, 34)
        downloaded = client.resolve_image(result.images[0])
        self.assertEqual(downloaded, image_data)
        self.assertIsNone(captured["download_auth"])

    def test_multiple_base64_images(self) -> None:
        first = base64.b64encode(png_bytes((1, 2, 3))).decode("ascii")
        second = base64.b64encode(png_bytes((4, 5, 6))).decode("ascii")
        client = NanoBananaClient(
            lambda: self.key,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"data": [{"b64_json": first}, {"b64_json": second}]},
                )
            ),
        )
        result = client.generate(self._request())
        self.assertEqual(len(result.images), 2)
        self.assertEqual(client.resolve_image(result.images[0]), base64.b64decode(first))
        self.assertEqual(client.resolve_image(result.images[1]), base64.b64decode(second))

    def test_invalid_base64_is_rejected(self) -> None:
        client = NanoBananaClient(
            lambda: self.key,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"data": [{"b64_json": "not-base64!!!"}]}
                )
            ),
        )
        result = client.generate(self._request())
        with self.assertRaises(ApiError):
            client.resolve_image(result.images[0])

    def test_missing_image_fields(self) -> None:
        client = NanoBananaClient(
            lambda: self.key,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": [{"revised_prompt": "x"}]})
            ),
        )
        with self.assertRaises(ApiError) as caught:
            client.generate(self._request())
        self.assertEqual(caught.exception.error_code, "missing_images")

    def test_invalid_json(self) -> None:
        client = NanoBananaClient(
            lambda: self.key,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=b"<html>bad gateway</html>",
                    headers={"content-type": "text/html"},
                )
            ),
        )
        with self.assertRaises(ApiError) as caught:
            client.generate(self._request())
        self.assertEqual(caught.exception.error_code, "invalid_json")

    def test_401_429_500_and_request_id(self) -> None:
        for status, expected in (
            (401, "API Key 无效"),
            (429, "稍后手动重试"),
            (500, "服务端繁忙"),
        ):
            with self.subTest(status=status):
                client = NanoBananaClient(
                    lambda: self.key,
                    transport=httpx.MockTransport(
                        lambda request, status=status: httpx.Response(
                            status,
                            json={"error": {"message": "服务端繁忙"}},
                            headers={"X-Request-Id": f"req-{status}"},
                        )
                    ),
                )
                with self.assertRaises(ApiError) as caught:
                    client.generate(self._request())
                self.assertEqual(caught.exception.status_code, status)
                self.assertEqual(caught.exception.request_id, f"req-{status}")
                self.assertIn(expected, caught.exception.message)

    def test_download_retries_twice_then_succeeds(self) -> None:
        attempts = {"count": 0}

        def get_handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ConnectError("temporary", request=request)
            return httpx.Response(200, content=png_bytes())

        client = NanoBananaClient(
            lambda: self.key,
            download_transport=httpx.MockTransport(get_handler),
        )
        image = client.resolve_image(
            __import__("yixin.models", fromlist=["RemoteImage"]).RemoteImage(
                url="https://files.example/a.png"
            ),
            sleep=lambda _: None,
        )
        self.assertEqual(attempts["count"], 3)
        self.assertTrue(image.startswith(b"\x89PNG"))

    def test_download_404_does_not_retry(self) -> None:
        attempts = {"count": 0}

        def get_handler(request: httpx.Request) -> httpx.Response:
            attempts["count"] += 1
            return httpx.Response(404)

        client = NanoBananaClient(
            lambda: self.key,
            download_transport=httpx.MockTransport(get_handler),
        )
        from yixin.models import RemoteImage

        with self.assertRaises(ApiError):
            client.resolve_image(RemoteImage(url="https://files.example/missing.png"))
        self.assertEqual(attempts["count"], 1)


if __name__ == "__main__":
    unittest.main()
