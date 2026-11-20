
"""Application entry point for Tarkov Wiki Lite."""

import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import TarkovWikiLite


def main() -> int:
    """Initialize and start the application."""

    app = QApplication(sys.argv)

    window = TarkovWikiLite()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
