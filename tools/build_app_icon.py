from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SVG_PATH = ASSETS / "app_icon.svg"
PNG_PATH = ASSETS / "app_icon.png"
ICO_PATH = ASSETS / "app_icon.ico"
PREVIEW_PATH = ASSETS / "icon_preview.png"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_svg(size: int) -> Image.Image:
    app = QGuiApplication.instance() or QGuiApplication([])
    _ = app
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError("SVG 图标无法加载")
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    buffer = image.bits().tobytes()
    return Image.frombuffer(
        "RGBA",
        (size, size),
        buffer,
        "raw",
        "BGRA",
        image.bytesPerLine(),
        1,
    ).copy()


def create_preview(master: Image.Image) -> None:
    canvas = Image.new("RGBA", (1600, 1320), (243, 246, 251, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((64, 20, 1536, 620), radius=28, fill="#F3F6FB")
    draw.rounded_rectangle((64, 660, 1536, 1260), radius=28, fill="#10182B")
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    except OSError:
        font = ImageFont.load_default()

    for panel_top, text_color in ((20, "#243044"), (660, "#E8F1FF")):
        label_y = panel_top + 35
        center_y = panel_top + 320
        x = 92
        for size in (16, 24, 32, 48, 64, 128):
            icon = master.resize((size, size), Image.Resampling.LANCZOS)
            canvas.alpha_composite(icon, (x, center_y - size // 2))
            label = f"{size}px"
            box = draw.textbbox((0, 0), label, font=font)
            draw.text(
                (x + (max(size, 70) - (box[2] - box[0])) / 2, label_y),
                label,
                fill=text_color,
                font=font,
            )
            x += max(size, 70) + 18
        for x, size in ((760, 256), (1080, 512)):
            icon = master.resize((size, size), Image.Resampling.LANCZOS)
            canvas.alpha_composite(icon, (x, center_y - size // 2))
            label = f"{size}px"
            box = draw.textbbox((0, 0), label, font=font)
            draw.text(
                (x + (size - (box[2] - box[0])) / 2, label_y),
                label,
                fill=text_color,
                font=font,
            )
    canvas.convert("RGB").save(PREVIEW_PATH, format="PNG", optimize=True)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = render_svg(512)
    master.save(PNG_PATH, format="PNG", optimize=True)
    master.save(
        ICO_PATH,
        format="ICO",
        sizes=[(size, size) for size in ICO_SIZES],
    )
    create_preview(master)
    print(PNG_PATH)
    print(ICO_PATH)
    print(PREVIEW_PATH)


if __name__ == "__main__":
    main()
