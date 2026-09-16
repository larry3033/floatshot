"""System tray icon and menu."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap

from .config import Config


def build_tray_icon(config: Config) -> QIcon:
    """Draw a simple camera-ish glyph so no image asset is needed.

    Every size and colour comes from the `icon` section of the config, so
    this module holds no literal of its own.
    """
    icon = config.get("icon")
    size = max(1, int(icon["size"]))

    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = pm.rect().adjusted(
            int(icon["body_margin_left"]),
            int(icon["body_margin_top"]),
            -int(icon["body_margin_right"]),
            -int(icon["body_margin_bottom"]),
        )
        radius = float(icon["corner_radius"])
        painter.setPen(QPen(QColor(icon["body_outline_color"]),
                            int(icon["outline_px"])))
        painter.setBrush(QColor(icon["body_color"]))
        painter.drawRoundedRect(body, radius, radius)

        lens = int(icon["lens_diameter_px"])
        painter.setBrush(QColor(icon["lens_color"]))
        painter.setPen(Qt.PenStyle.NoPen)
        cx, cy = body.center().x(), body.center().y()
        painter.drawEllipse(cx - lens // 2, cy - lens // 2, lens, lens)
    finally:
        painter.end()

    return QIcon(pm)


class Tray(QObject):
    """Owns the tray icon and translates menu picks into signals."""

    capture_requested = Signal()
    diagnostics_requested = Signal()
    quit_requested = Signal()

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        self._config = config
        self._icon = QSystemTrayIcon(build_tray_icon(config), self)
        self._icon.setToolTip("FloatShot")

        menu = QMenu()
        # Show the configured hotkey in the menu: the user may have changed
        # it in config.json, and this is the only place it is visible.
        act_capture = QAction(f"截屏（{config.get('hotkey')}）", menu)
        act_diag = QAction("诊断信息", menu)
        act_quit = QAction("退出", menu)

        act_capture.triggered.connect(self.capture_requested.emit)
        act_diag.triggered.connect(self.diagnostics_requested.emit)
        act_quit.triggered.connect(self.quit_requested.emit)

        menu.addAction(act_capture)
        menu.addSeparator()
        menu.addAction(act_diag)
        menu.addSeparator()
        menu.addAction(act_quit)
        self._menu = menu
        self._icon.setContextMenu(menu)

        # Left-click should also start a capture, matching common tools.
        self._icon.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.capture_requested.emit()

    def show(self) -> None:
        self._icon.show()

    def notify(self, title: str, message: str) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon

        self._icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)
