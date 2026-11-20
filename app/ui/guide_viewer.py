
"""Lightweight quest image gallery with zoom."""

from PySide6.QtCore import Qt, QSize, QTimer, QUrl
from PySide6.QtGui import (
    QDesktopServices,
    QImageReader,
    QPixmap,
    QPainter,
)
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.services.guide_images import GuideImageCache


class ZoomView(QGraphicsView):
    """Zoomable image view with mouse-wheel support."""

    def __init__(self, scene):
        super().__init__(scene)

        self.zoom_level = 1.0
        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )

    def zoom_by(self, factor: float):
        new_level = self.zoom_level * factor

        if 0.25 <= new_level <= 5.0:
            self.scale(factor, factor)
            self.zoom_level = new_level

    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        self.zoom_by(factor)
        event.accept()

    def fit_image(self):
        if self.scene() and not self.scene().sceneRect().isEmpty():
            self.fitInView(
                self.scene().sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            self.zoom_level = 1.0


class GuideDialog(QDialog):
    """Show curated quest images one at a time."""

    def __init__(
        self,
        quest_name: str,
        images: list[dict],
        cache: GuideImageCache,
        parent=None,
    ):
        super().__init__(parent)

        self.images = images
        self.cache = cache
        self.index = 0

        self.setWindowTitle(f"Location Guide - {quest_name}")
        self.resize(950, 680)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.title = QLabel()
        self.title.setStyleSheet(
            "font-size: 19px; font-weight: bold;"
            "color: #bdd393;"
        )
        layout.addWidget(self.title)

        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.scene = QGraphicsScene(self)
        self.image_item = QGraphicsPixmapItem()
        self.scene.addItem(self.image_item)

        self.viewer = ZoomView(self.scene)
        layout.addWidget(self.viewer, 1)

        self.status = QLabel()
        layout.addWidget(self.status)

        controls = QHBoxLayout()

        previous = QPushButton("Previous")
        previous.clicked.connect(self.previous_image)
        controls.addWidget(previous)
        self.previous_button = previous

        self.page_label = QLabel()
        controls.addWidget(self.page_label)

        next_button = QPushButton("Next")
        next_button.clicked.connect(self.next_image)
        controls.addWidget(next_button)
        self.next_button = next_button

        controls.addStretch()

        zoom_out = QPushButton("-")
        zoom_out.clicked.connect(
            lambda: self.viewer.zoom_by(1 / 1.25)
        )
        controls.addWidget(zoom_out)

        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(
            lambda: self.viewer.zoom_by(1.25)
        )
        controls.addWidget(zoom_in)

        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(self.viewer.fit_image)
        controls.addWidget(fit_button)

        source_button = QPushButton("Source")
        source_button.clicked.connect(self.open_source)
        controls.addWidget(source_button)

        layout.addLayout(controls)

        self.setStyleSheet("""
            QDialog {
                background: #151e23;
                color: #e6ecef;
            }

            QLabel {
                color: #e6ecef;
            }

            QGraphicsView {
                background: #10171b;
                border: 1px solid #405348;
            }

            QPushButton {
                background: #263238;
                color: #e6ecef;
                border: 1px solid #405348;
                border-radius: 5px;
                padding: 8px 12px;
            }

            QPushButton:hover {
                background: #3b5144;
            }
        """)

        self.show_image()

    def show_image(self):
        image = self.images[self.index]

        self.title.setText(image["title"])
        self.description.setText(image["description"])

        self.page_label.setText(
            f"{self.index + 1} / {len(self.images)}"
        )

        self.previous_button.setEnabled(self.index > 0)
        self.next_button.setEnabled(
            self.index < len(self.images) - 1
        )

        # Release the previous image from the view
        self.image_item.setPixmap(QPixmap())
        self.scene.setSceneRect(self.image_item.boundingRect())

        self.status.setText("Loading image...")

        requested_index = self.index

        self.cache.load(
            image["url"],
            lambda path, error: self.image_loaded(
                requested_index, path, error
            ),
        )

    def image_loaded(self, index, path, error):
        if index != self.index:
            return

        if error or path is None:
            self.status.setText(
                f"Image unavailable: {error}"
            )
            return

        reader = QImageReader(str(path))
        size = reader.size()

        if not size.isValid():
            self.status.setText("Invalid image dimensions.")
            return

        # Decode at a bounded resolution to save RAM
        max_dimension = 2200
        scale = min(
            1.0,
            max_dimension / max(size.width(), size.height()),
        )

        if scale < 1:
            reader.setScaledSize(QSize(
                max(1, round(size.width() * scale)),
                max(1, round(size.height() * scale)),
            ))

        decoded = reader.read()

        if decoded.isNull():
            self.status.setText(reader.errorString())
            return

        self.image_item.setPixmap(
            QPixmap.fromImage(decoded)
        )
        self.scene.setSceneRect(
            self.image_item.boundingRect()
        )

        self.status.setText(
            "Use the mouse wheel to zoom. Drag to pan."
        )

        QTimer.singleShot(0, self.viewer.fit_image)

    def previous_image(self):
        if self.index > 0:
            self.index -= 1
            self.show_image()

    def next_image(self):
        if self.index < len(self.images) - 1:
            self.index += 1
            self.show_image()

    def open_source(self):
        source = self.images[self.index].get("source")

        if source:
            QDesktopServices.openUrl(QUrl(source))
