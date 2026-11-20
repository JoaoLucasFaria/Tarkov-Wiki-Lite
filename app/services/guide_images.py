
"""On-demand image downloads with a bounded disk cache."""

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QImageReader
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)


MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_CACHE_BYTES = 500 * 1024 * 1024


class GuideImageCache(QObject):
    """Download curated images without blocking the UI."""

    def __init__(self, cache_dir: Path, parent=None):
        super().__init__(parent)

        self.cache_dir = Path(cache_dir)
        self.network = QNetworkAccessManager(self)
        self.pending = {}

    def _trim_cache(self, incoming: int) -> None:
        files = sorted(
            self.cache_dir.glob("*.img"),
            key=lambda path: path.stat().st_mtime,
        )

        total = sum(path.stat().st_size for path in files)

        for path in files:
            if total + incoming <= MAX_CACHE_BYTES:
                break

            size = path.stat().st_size
            path.unlink()
            total -= size

    def load(self, url: str, callback) -> None:
        """Return a cached image or download it asynchronously."""

        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname != "static.wikia.nocookie.net"
        ):
            callback(None, "Image source is not permitted.")
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        image_hash = hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()

        path = self.cache_dir / f"{image_hash}.img"

        if path.is_file():
            if QImageReader(str(path)).canRead():
                path.touch()
                callback(path, None)
                return

            path.unlink(missing_ok=True)

        if url in self.pending:
            self.pending[url].append(callback)
            return

        self.pending[url] = [callback]

        temp_path = path.with_suffix(".part")

        try:
            output = temp_path.open("wb")
        except OSError as error:
            callbacks = self.pending.pop(url, [])
            for fn in callbacks:
                fn(None, str(error))
            return

        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(20000)
        request.setRawHeader(
            b"User-Agent", b"Mozilla/5.0 TarkovWikiLite/0.4"
        )
        request.setRawHeader(
            b"Referer",
            b"https://escapefromtarkov.fandom.com/",
        )

        reply = self.network.get(request)
        received = 0
        oversized = False

        def read_chunks():
            nonlocal received, oversized

            chunk = bytes(reply.readAll())
            received += len(chunk)

            if received > MAX_IMAGE_BYTES:
                oversized = True
                reply.abort()
                return

            if not oversized:
                output.write(chunk)

        def finished():
            error_message = None

            try:
                read_chunks()
                output.close()

                if oversized:
                    error_message = "Image exceeds the 12 MB limit."

                elif (
                    reply.error()
                    != QNetworkReply.NetworkError.NoError
                ):
                    error_message = reply.errorString()

                elif not QImageReader(str(temp_path)).canRead():
                    error_message = "Invalid or unsupported image."

                else:
                    size = temp_path.stat().st_size
                    self._trim_cache(size)
                    temp_path.replace(path)

            except OSError as error:
                error_message = str(error)

            finally:
                if not output.closed:
                    output.close()

                temp_path.unlink(missing_ok=True)
                reply.deleteLater()

            callbacks = self.pending.pop(url, [])

            for fn in callbacks:
                fn(
                    path if error_message is None else None,
                    error_message,
                )

        reply.readyRead.connect(read_chunks)
        reply.finished.connect(finished)
