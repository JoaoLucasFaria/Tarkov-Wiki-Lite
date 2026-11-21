"""Offline test for item image decoding (including WebP fallback).

Run from project root: python -m tools.test_item_image_decode
"""

from io import BytesIO

from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication

from app.services.item_image_decoder import decode_item_pixmap


app = QApplication.instance() or QApplication([])
formats = sorted(bytes(fmt).decode('ascii', 'replace') for fmt in QImageReader.supportedImageFormats())
print('Qt image formats:', ', '.join(formats))

try:
    from PIL import Image
except ImportError:
    print('Pillow not installed. To enable fallback: python -m pip install Pillow')
    raise SystemExit(1)

for format_name in ('PNG', 'WEBP'):
    source = Image.new('RGB', (128, 96), color=(50, 120, 80))
    raw = BytesIO()
    source.save(raw, format=format_name)
    pixmap, error = decode_item_pixmap(raw.getvalue())
    assert pixmap is not None and not pixmap.isNull(), (
        f'{format_name} decoding failed: {error}'
    )
    print(f'PASS: {format_name} ({pixmap.width()}x{pixmap.height()})')

print('All item image decoding tests passed!')
