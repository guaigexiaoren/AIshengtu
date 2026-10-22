from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QImageReader,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .widgets import load_scaled_pixmap


class CropCanvas(QWidget):
    HANDLE_SIZE = 10
    MIN_NORMALIZED_SIZE = 0.01

    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.image_path = image_path
        self._pixmap = load_scaled_pixmap(image_path, QSize(960, 660), cache=False)
        reader = QImageReader(str(image_path))
        reader.setAutoTransform(True)
        self.source_size = reader.size()
        if self._pixmap.isNull() or not self.source_size.isValid():
            raise ValueError("无法读取要裁剪的图片")
        self._crop = QRectF(0.0, 0.0, 1.0, 1.0)
        self._mode = ""
        self._drag_start = QPointF()
        self._start_crop = QRectF()
        self.setMinimumSize(560, 420)
        self.setMouseTracking(True)

    def reset_crop(self) -> None:
        self._crop = QRectF(0.0, 0.0, 1.0, 1.0)
        self.update()

    def crop_box(self) -> tuple[int, int, int, int]:
        width = self.source_size.width()
        height = self.source_size.height()
        left = max(0, min(round(self._crop.left() * width), width - 1))
        top = max(0, min(round(self._crop.top() * height), height - 1))
        right = max(left + 1, min(round(self._crop.right() * width), width))
        bottom = max(top + 1, min(round(self._crop.bottom() * height), height))
        return left, top, right, bottom

    def _image_rect(self) -> QRectF:
        available = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        ratio = min(
            available.width() / max(1, self.source_size.width()),
            available.height() / max(1, self.source_size.height()),
        )
        target = QRectF(
            0,
            0,
            self.source_size.width() * ratio,
            self.source_size.height() * ratio,
        )
        target.moveCenter(available.center())
        return target

    def _crop_rect(self) -> QRectF:
        image_rect = self._image_rect()
        return QRectF(
            image_rect.left() + self._crop.left() * image_rect.width(),
            image_rect.top() + self._crop.top() * image_rect.height(),
            self._crop.width() * image_rect.width(),
            self._crop.height() * image_rect.height(),
        )

    def _handles(self) -> dict[str, QPointF]:
        crop = self._crop_rect()
        return {
            "nw": crop.topLeft(),
            "n": QPointF(crop.center().x(), crop.top()),
            "ne": crop.topRight(),
            "e": QPointF(crop.right(), crop.center().y()),
            "se": crop.bottomRight(),
            "s": QPointF(crop.center().x(), crop.bottom()),
            "sw": crop.bottomLeft(),
            "w": QPointF(crop.left(), crop.center().y()),
        }

    def _point_in_image(self, point: QPointF) -> bool:
        return self._image_rect().contains(point)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#111827"))
        image_rect = self._image_rect()
        target = QRectF(self._pixmap.rect())
        target.moveCenter(image_rect.center())
        painter.drawPixmap(target.toRect(), self._pixmap)

        crop = self._crop_rect()
        shade = QColor(0, 0, 0, 145)
        painter.fillRect(
            QRectF(image_rect.left(), image_rect.top(), image_rect.width(), crop.top() - image_rect.top()),
            shade,
        )
        painter.fillRect(
            QRectF(image_rect.left(), crop.bottom(), image_rect.width(), image_rect.bottom() - crop.bottom()),
            shade,
        )
        painter.fillRect(
            QRectF(image_rect.left(), crop.top(), crop.left() - image_rect.left(), crop.height()),
            shade,
        )
        painter.fillRect(
            QRectF(crop.right(), crop.top(), image_rect.right() - crop.right(), crop.height()),
            shade,
        )
        painter.setPen(QPen(QColor("#65E6FF"), 2))
        painter.drawRect(crop)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for fraction in (1 / 3, 1 / 2, 2 / 3):
            x = crop.left() + crop.width() * fraction
            y = crop.top() + crop.height() * fraction
            painter.drawLine(QPointF(x, crop.top()), QPointF(x, crop.bottom()))
            painter.drawLine(QPointF(crop.left(), y), QPointF(crop.right(), y))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(QColor("#2E64C4"))
        half = self.HANDLE_SIZE / 2
        for point in self._handles().values():
            painter.drawRect(
                QRectF(point.x() - half, point.y() - half, self.HANDLE_SIZE, self.HANDLE_SIZE)
            )

    def _hit_test(self, point: QPointF) -> str:
        threshold = self.HANDLE_SIZE
        for name, handle in self._handles().items():
            if (
                abs(point.x() - handle.x()) <= threshold
                and abs(point.y() - handle.y()) <= threshold
            ):
                return name
        if self._crop_rect().contains(point):
            return "move"
        if self._point_in_image(point):
            return "new"
        return ""

    def _normalize_point(self, point: QPointF) -> QPointF:
        image_rect = self._image_rect()
        return QPointF(
            max(0.0, min(1.0, (point.x() - image_rect.left()) / image_rect.width())),
            max(0.0, min(1.0, (point.y() - image_rect.top()) / image_rect.height())),
        )

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._mode = self._hit_test(event.position())
        if not self._mode:
            return
        self._drag_start = event.position()
        self._start_crop = QRectF(self._crop)
        if self._mode == "new":
            point = self._normalize_point(event.position())
            self._crop = QRectF(point, point)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self._mode:
            self.setCursor(self._cursor_for_mode(self._hit_test(event.position())))
            return
        point = self._normalize_point(event.position())
        if self._mode == "move":
            image_rect = self._image_rect()
            dx = (event.position().x() - self._drag_start.x()) / image_rect.width()
            dy = (event.position().y() - self._drag_start.y()) / image_rect.height()
            left = max(0.0, min(1.0 - self._start_crop.width(), self._start_crop.left() + dx))
            top = max(0.0, min(1.0 - self._start_crop.height(), self._start_crop.top() + dy))
            self._crop = QRectF(left, top, self._start_crop.width(), self._start_crop.height())
        elif self._mode == "new":
            start = self._normalize_point(self._drag_start)
            self._crop = QRectF(start, point).normalized()
        else:
            left = self._start_crop.left()
            top = self._start_crop.top()
            right = self._start_crop.right()
            bottom = self._start_crop.bottom()
            if "w" in self._mode:
                left = point.x()
            if "e" in self._mode:
                right = point.x()
            if "n" in self._mode:
                top = point.y()
            if "s" in self._mode:
                bottom = point.y()
            self._crop = QRectF(
                min(left, right), min(top, bottom),
                abs(right - left), abs(bottom - top),
            ).normalized()
        if (
            self._crop.width() < self.MIN_NORMALIZED_SIZE
            or self._crop.height() < self.MIN_NORMALIZED_SIZE
        ):
            self._crop = QRectF(self._start_crop)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        self._mode = ""
        self.unsetCursor()
        self.update()

    @staticmethod
    def _cursor_for_mode(mode: str):
        return {
            "nw": Qt.CursorShape.SizeFDiagCursor,
            "se": Qt.CursorShape.SizeFDiagCursor,
            "ne": Qt.CursorShape.SizeBDiagCursor,
            "sw": Qt.CursorShape.SizeBDiagCursor,
            "n": Qt.CursorShape.SizeVerCursor,
            "s": Qt.CursorShape.SizeVerCursor,
            "e": Qt.CursorShape.SizeHorCursor,
            "w": Qt.CursorShape.SizeHorCursor,
            "move": Qt.CursorShape.SizeAllCursor,
            "new": Qt.CursorShape.CrossCursor,
        }.get(mode, Qt.CursorShape.ArrowCursor)


class CropDialog(QDialog):
    def __init__(self, image_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("裁剪参考图")
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        tip = QLabel(
            "拖动蓝色框或八个控制点调整裁剪范围；本次裁剪只影响下一次生成。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)
        try:
            self.canvas = CropCanvas(image_path, self)
        except ValueError as exc:
            QMessageBox.warning(self, "无法裁剪", str(exc))
            self.canvas = None
        if self.canvas:
            layout.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        reset = QPushButton("整图")
        cancel = QPushButton("取消")
        apply_button = QPushButton("应用裁剪")
        apply_button.setObjectName("PrimaryButton")
        footer.addWidget(reset)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(apply_button)
        layout.addLayout(footer)
        reset.clicked.connect(self.canvas.reset_crop if self.canvas else lambda: None)
        cancel.clicked.connect(self.reject)
        apply_button.clicked.connect(self._apply)

    def crop_box(self) -> tuple[int, int, int, int] | None:
        return self.canvas.crop_box() if self.canvas else None

    def _apply(self) -> None:
        if self.canvas is None:
            self.reject()
            return
        left, top, right, bottom = self.canvas.crop_box()
        if right - left < 2 or bottom - top < 2:
            QMessageBox.warning(self, "裁剪范围过小", "请选择更大的图片区域。")
            return
        self.accept()
