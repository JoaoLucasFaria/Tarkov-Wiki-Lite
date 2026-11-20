
"""HTTP client for Tarkov Wiki Lite."""

import json
from collections.abc import Callable

from PySide6.QtCore import QObject, QUrl
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)


JsonCallback = Callable[
    [object | None, str | None],
    None
]


class TarkovApi(QObject):
    """Handle asynchronous HTTP requests."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.network = QNetworkAccessManager(self)

    def get_json(
        self,
        url: str,
        callback: JsonCallback
    ) -> None:
        """Fetch JSON without blocking the interface."""

        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(20000)

        reply = self.network.get(request)

        def on_finished() -> None:
            try:
                if (
                    reply.error()
                    != QNetworkReply.NetworkError.NoError
                ):
                    callback(None, reply.errorString())
                    return

                data = json.loads(
                    bytes(reply.readAll()).decode("utf-8")
                )

                callback(data, None)

            except (ValueError, UnicodeError) as error:
                callback(None, str(error))

            finally:
                reply.deleteLater()

        reply.finished.connect(on_finished)
