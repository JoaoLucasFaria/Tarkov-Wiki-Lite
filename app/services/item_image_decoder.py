"""Decode small item illustrations with an optional WebP fallback.

Qt's image formats depend on deployed plugins. Some lean PySide6 builds
lack the WebP image plugin; Pillow is only imported if Qt cannot decode.
"""

from __future__ import annotations

from io import BytesIO

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap


MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 12_000_000


def decode_item_pixmap(
    data: bytes,
    target_size: int = 144,
) -> tuple[QPixmap | None, str | None]:
    """Return a thumbnail pixmap or a diagnostic error message."""

    if not data:
        return None, "Empty image response"

    # First try Qt's native reader (fast, and no Pillow imported).
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    source = reader.size()
    qt_error = ""

    if source.isValid():
        width = source.width()
        height = source.height()
        if (
            width > MAX_IMAGE_DIMENSION
            or height > MAX_IMAGE_DIMENSION
            or width * height > MAX_IMAGE_PIXELS
        ):
            return None, "Image dimensions exceed safety limits"

        reader.setScaledSize(
            source.scaled(
                QSize(target_size, target_size),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        )
        decoded = reader.read()
        if not decoded.isNull():
            return QPixmap.fromImage(decoded), None
        qt_error = reader.errorString() or "Qt could not decode image"
    else:
        qt_error = reader.errorString() or "Qt format unavailable"

    # WebP is distributed via a separate imageformat plugin on some Qt
    # installations. Pillow fallback is loaded ONLY on a failed Qt decode.
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return None, (
            f"Qt decode failed ({qt_error}). "
            "WebP support may be missing; run: python -m pip install Pillow"
        )

    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                return None, "Image dimensions exceed safety limits"
            image.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
            rgba = image.convert("RGBA")
            pixels = rgba.tobytes()
            width, height = rgba.size
            # copy() takes ownership: pixels can go out of scope safely.
            qimage = QImage(
                pixels,
                width,
                height,
                4 * width,
                QImage.Format.Format_RGBA8888,
            ).copy()
            if qimage.isNull():
                return None, "Could not convert decoded image to Qt"
            return QPixmap.fromImage(qimage), None
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as error:
        return None, f"Qt: {qt_error}; Pillow: {error}"
