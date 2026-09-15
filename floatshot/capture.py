"""Screen capture across all monitors.

Uses QScreen.grabWindow rather than an external capture library so that
PySide6 remains the only runtime dependency (this app ships as a
standalone exe).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap


def virtual_geometry() -> QRect:
    """Bounding rect of every screen, in physical pixels.

    May have a negative origin when a secondary monitor sits left of or
    above the primary one.
    """
    rect = QRect()
    for screen in QGuiApplication.screens():
        rect = rect.united(screen.geometry())
    return rect


def grab_virtual_desktop() -> tuple[QPixmap, QRect]:
    """Capture every screen into a single pixmap.

    Returns (canvas, origin) where `origin` is the virtual desktop rect.
    A point p on the desktop maps to p - origin.topLeft() on the canvas.
    """
    origin = virtual_geometry()
    if origin.isEmpty():
        return QPixmap(), origin

    canvas = QPixmap(origin.size())
    canvas.fill(Qt.GlobalColor.black)

    painter = QPainter(canvas)
    try:
        for screen in QGuiApplication.screens():
            geo = screen.geometry()
            shot = screen.grabWindow(0)
            if shot.isNull():
                continue
            painter.drawPixmap(geo.topLeft() - origin.topLeft(), shot)
    finally:
        painter.end()

    return canvas, origin


def crop(pixmap: QPixmap, region: QRect, origin: QRect) -> QPixmap:
    """Cut `region` (desktop coordinates) out of a virtual-desktop canvas."""
    local = region.translated(-origin.topLeft())
    return pixmap.copy(local)
