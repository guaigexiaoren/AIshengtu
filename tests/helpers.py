from __future__ import annotations

import io
from pathlib import Path

from PIL import Image


def png_bytes(
    color: tuple[int, int, int] = (40, 100, 190),
    size: tuple[int, int] = (64, 80),
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def make_image(path: Path, color: tuple[int, int, int] = (40, 100, 190)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(color))
    return path
