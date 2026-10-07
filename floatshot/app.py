"""Wires the hotkey, overlay, capture and floating windows together."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRect, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMessageBox

from . import DPI_AWARENESS_STATUS
from .capture import crop, grab_virtual_desktop, virtual_geometry
from .config import Config
from .dpi import query_system_dpi, ui_scale
from .float_window import FloatWindow
from .hotkey import GlobalHotkey
from .hotkey_spec import HotkeyParseError, parse_hotkey
from .metrics import compute_metrics
from .overlay import SelectionOverlay
from .settings_window import SettingsWindow
from .tray import Tray


class FloatShotApp(QObject):
    """Owns the application lifecycle."""

    def __init__(self, app: QApplication, config: Config) -> None:
        super().__init__()
        self._app = app
        self._config = config
        self._windows: list[FloatWindow] = []
        self._overlay: SelectionOverlay | None = None
        self._overlay_shortcut: QShortcut | None = None
        self._pending: tuple[object, QRect] | None = None

        self._activation_attempts = 0
        self._activation_timer = QTimer(self)
        self._activation_timer.setInterval(int(config.get("activation", "retry_ms")))
        self._activation_timer.timeout.connect(self._retry_activation)

        self._tray = Tray(config, self)

        self._hotkey = GlobalHotkey(self)
        self._hotkey.activated.connect(self.start_capture)

        # The configuration window is the main interface. It edits the shared
        # Config directly and signals back for the few live side effects.
        # Parentless: it is a top-level window, not a child of this QObject.
        self._settings = SettingsWindow(config)
        self._settings.capture_requested.connect(self.start_capture)
        self._settings.diagnostics_requested.connect(self.show_diagnostics)
        self._settings.hotkey_changed.connect(self._apply_hotkey)
        self._settings.quit_requested.connect(self.quit)
        self._tray.open_requested.connect(self.show_settings)
        self._tray.quit_requested.connect(self.quit)

        # Whether the settings window was hidden for a capture and must return.
        self._restore_settings = False

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._tray.show()
        if not self._register_hotkey():
            self._tray.notify(
                "FloatShot",
                f"热键注册失败：{self._hotkey.last_error}\n"
                f"可在配置界面中修改快捷键。",
            )
        # "Launching goes straight into the configuration interface."
        self.show_settings()

    def show_settings(self) -> None:
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _register_hotkey(self) -> bool:
        spec = str(self._config.get("hotkey"))
        try:
            hotkey = parse_hotkey(spec)
        except HotkeyParseError as exc:
            self._hotkey.last_error = str(exc)
            return False
        return self._hotkey.register(hotkey)

    def _apply_hotkey(self, spec: str) -> None:
        """Register a hotkey the settings window just stored."""
        if self._register_hotkey():
            self._settings.show_hotkey_status(True, f"已生效：{spec}")
        else:
            self._settings.show_hotkey_status(
                False, f"注册失败：{self._hotkey.last_error}")

    def quit(self) -> None:
        self._hotkey.unregister()
        for window in list(self._windows):
            window.close()
        self._app.quit()

    # -- capture flow ------------------------------------------------------

    def start_capture(self) -> None:
        """Hotkey entry point: capture first, then show the overlay.

        Capturing before the overlay appears is what keeps the darkened
        backdrop and selection border out of the resulting screenshot, and
        avoids the flicker of hide-then-grab.
        """
        if self._overlay is not None:
            return  # a selection is already in progress

        # The settings window is the main interface now, so it would end up
        # inside every screenshot unless it gets out of the way first. Hide
        # it and let the paint settle before grabbing.
        if self._settings.isVisible():
            self._restore_settings = True
            self._settings.hide()
            self._app.processEvents()

        canvas, origin = grab_virtual_desktop()
        if canvas.isNull():
            self._restore_settings_window()
            self._tray.notify("FloatShot", "抓屏失败：未获取到画面。")
            return

        self._pending = (canvas, origin)
        self._overlay = SelectionOverlay(virtual_geometry(), self._config)
        self._overlay.selected.connect(self._on_selected)
        self._overlay.cancelled.connect(self._on_cancelled)
        # Esc cancels the selection.  The overlay's own keyPressEvent only
        # receives the key while the overlay holds Qt's keyboard focus, so an
        # application-wide shortcut adds the case where our application is
        # active but the overlay is not the focused widget.  It does *not*
        # cover a SetForegroundWindow that Windows refused -- no key event
        # reaches us at all then -- so the defence against that is the
        # activation retry below, not this shortcut.
        #
        # `activated` is routed into the overlay's single cancel entry point
        # rather than straight to _on_cancelled, so Esc takes exactly the same
        # path as the overlay's keyPressEvent and its right-click: the drag
        # anchor is dropped and `cancelled` is announced exactly once.
        self._overlay_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape),
                                           self._overlay)
        self._overlay_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._overlay_shortcut.activated.connect(self._overlay._cancel)
        self._activation_attempts = 0
        self._overlay.show()
        self._claim_foreground()
        self._activation_timer.start()

    def _claim_foreground(self) -> None:
        """Ask for the keyboard, then keep asking until we actually have it.

        `activateWindow()` is `SetForegroundWindow`, which Windows may refuse
        *silently* when this process is not entitled to the foreground -- the
        normal case, since the user pressed the hotkey while another
        application was active.  The overlay cancels on Esc, and Esc needs the
        keyboard, so a refused activation would strand a full-screen window
        the user cannot dismiss.  Hence: set focus within the window as well
        as activating it, and re-ask on a timer instead of asking once.
        """
        overlay = self._overlay
        if overlay is None:
            return
        overlay.raise_()
        overlay.activateWindow()
        overlay.setFocus(Qt.FocusReason.OtherFocusReason)
        self._activation_attempts += 1

    def _retry_activation(self) -> None:
        """Re-assert the activation request whenever the overlay has lost it.

        This keeps checking for as long as the selection is in progress --
        focus can be lost again after a successful first attempt -- but the
        number of times it will actually *ask* is capped, so a user who
        deliberately puts another window in front during a selection is not
        fought indefinitely.
        """
        overlay = self._overlay
        if overlay is None:
            self._activation_timer.stop()
            return
        if self._activation_attempts >= int(self._config.get(
                "activation", "max_attempts")):
            self._activation_timer.stop()
            return
        if overlay.isActiveWindow() and overlay.hasFocus():
            return
        self._claim_foreground()

    def _on_cancelled(self) -> None:
        self._pending = None
        self._dispose_overlay()

    def _dispose_overlay(self) -> None:
        self._activation_timer.stop()
        if self._overlay_shortcut is not None:
            # An application-wide shortcut outlives the widget being hidden,
            # so it has to be switched off explicitly, not just dropped.
            self._overlay_shortcut.setEnabled(False)
            self._overlay_shortcut = None
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        self._restore_settings_window()

    def _restore_settings_window(self) -> None:
        if self._restore_settings:
            self._restore_settings = False
            self.show_settings()

    def _on_selected(self, region: QRect) -> None:
        if self._pending is None:
            self._dispose_overlay()
            return

        canvas, origin = self._pending
        self._pending = None
        self._dispose_overlay()

        shot = crop(canvas, region, origin)
        if shot.isNull() or shot.width() < 2 or shot.height() < 2:
            return

        if self._config.get("capture", "copy_to_clipboard"):
            # QQ-style convenience: the region is on the clipboard before the
            # user even looks at the floating window.
            QGuiApplication.clipboard().setPixmap(shot)

        window = FloatWindow(shot, self._config)
        window.closed.connect(self._on_window_closed)
        # Place the picture exactly where the selection was, so it looks
        # like the selection turned into the floating window in place.
        pad = window.image_rect().x()
        window.move(region.x() - pad, region.y() - pad)
        window.show()
        self._windows.append(window)

    def _on_window_closed(self, window: FloatWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)

    # -- diagnostics -------------------------------------------------------

    def show_diagnostics(self) -> None:
        box = QMessageBox(self._settings)
        box.setWindowTitle("FloatShot 诊断信息")
        box.setText(self.diagnostics_text())
        box.setIcon(QMessageBox.Icon.Information)
        # Stay above the floating windows, otherwise the windows being
        # diagnosed would cover the report.
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()

    def diagnostics_text(self) -> str:
        """The values that cannot be verified on a single-DPI machine.

        This is the check to run on a 125% / 150% display before handing the
        build to someone else: the DPI figure must match that display's
        scaling, not sit at a constant 96.
        """
        scale = ui_scale()
        dpi_value = query_system_dpi()
        shadow = self._config.get("shadow")
        resize = self._config.get("resize")
        close = self._config.get("close_button")

        # Report metrics for a representative 400x300 picture.
        probe = compute_metrics(
            scale,
            400,
            300,
            shadow_padding=shadow["padding"],
            grip_ratio=resize["grip_ratio"],
            close_diameter_px=close["diameter_px"],
            close_hit_radius_factor=close["hit_radius_factor"],
        )

        geo = virtual_geometry()
        return "\n".join([
            f"DPI 感知声明：{DPI_AWARENESS_STATUS}",
            f"系统 DPI：{dpi_value}",
            f"缩放因子：{scale:.3f}  ({scale * 100:.0f}%)",
            "",
            f"热键：{self._config.get('hotkey')}",
            f"截图后复制到剪贴板："
            f"{'开' if self._config.get('capture', 'copy_to_clipboard') else '关'}",
            "",
            f"虚拟桌面：{geo.width()} x {geo.height()}  @ ({geo.x()}, {geo.y()})",
            "",
            "以 400x300 图片为例——",
            f"  阴影内边距：{probe.padding} px",
            f"  横向判定带：{probe.grip_x} px"
            f"（窗口宽的 {float(resize['grip_ratio']) * 100:.0f}%）",
            f"  纵向判定带：{probe.grip_y} px"
            f"（窗口高的 {float(resize['grip_ratio']) * 100:.0f}%）",
            f"  关闭按钮径：{probe.close_diameter} px",
            f"  按钮判定半径：{probe.close_hit_radius:.1f} px",
            "",
            f"悬浮窗数量：{len(self._windows)}",
        ])
