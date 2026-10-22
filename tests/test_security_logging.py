from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from yixin.logging_utils import (
    redact_data,
    register_sensitive_value,
    sanitize_text,
)
from yixin.security import SecretStore, mask_secret, validate_api_key


class SecurityAndLoggingTests(unittest.TestCase):
    def test_dpapi_round_trip_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "api_key.bin"
            store = SecretStore(path)
            key = "sk-secret-1234567890"
            store.save(key)
            self.assertTrue(path.exists())
            self.assertNotIn(key.encode("utf-8"), path.read_bytes())
            self.assertEqual(store.load(strict=True), key)
            self.assertIn("••••", mask_secret(key))
            store.clear()
            self.assertFalse(path.exists())
            self.assertIsNone(store.load())

    def test_api_key_format_validation(self) -> None:
        self.assertEqual(validate_api_key("  sk-1234567890  "), "sk-1234567890")
        with self.assertRaises(ValueError):
            validate_api_key("short")
        with self.assertRaises(ValueError):
            validate_api_key("sk-1234 567890")

    def test_sensitive_text_is_redacted(self) -> None:
        key = "sk-unique-secret-987654"
        register_sensitive_value(key)
        text = sanitize_text(
            f"Authorization: Bearer {key} key={key} "
            "https://files.example/a.png?token=abc&sig=def"
        )
        self.assertNotIn(key, text)
        self.assertNotIn("abc", text)
        self.assertNotIn("def", text)

    def test_data_redaction_preserves_usage_and_hides_images(self) -> None:
        payload = {
            "usage": {"input_tokens": 10, "output_tokens": 20},
            "api_key": "secret",
            "data": [{"b64_json": "data:image/png;base64,AAAA"}],
            "url": "https://files.example/a.png?signature=secret",
        }
        redacted = redact_data(payload)
        self.assertEqual(redacted["usage"]["input_tokens"], 10)
        self.assertEqual(redacted["usage"]["output_tokens"], 20)
        self.assertEqual(redacted["api_key"], "[已隐藏]")
        self.assertNotIn("AAAA", str(redacted))
        self.assertNotIn("signature=secret", redacted["url"])


if __name__ == "__main__":
    unittest.main()
