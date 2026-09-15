"""System-wide hotkey registration via Win32 RegisterHotKey.

Route in use: **thread message queue** (``hwnd=NULL``).  Registering with
hwnd=NULL binds the hotkey to this thread's message queue rather than to
a window, and Qt's ``QAbstractNativeEventFilter`` does observe those
thread messages, so no receiver window is needed.

That was the one assumption in the design that could not be settled by
reading the docs, so it was measured rather than assumed.  Injecting the
chord through the system input queue with ``keybd_event`` (the same path
a physical keypress takes) fired ``activated``, which proves the
``WM_HOTKEY`` for our id reached the filter with hwnd=NULL.  A wrong
chord (Ctrl+Alt+W) did not fire it, ruling out a spurious signal.  The
fallback -- passing ``int(widget.winId())`` to ``RegisterHotKey`` instead
of ``None``, and keeping that widget alive on the instance -- is NOT in
use; reach for it only if Qt changes how it pumps thread messages.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from .hotkey_spec import MOD_NOREPEAT, Hotkey

WM_HOTKEY = 0x0312

# Arbitrary but stable id, used to tell our hotkey apart from others.
_HOTKEY_ID = 0xA17E


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
    ]


class _HotkeyFilter(QAbstractNativeEventFilter):
    """Forwards WM_HOTKEY for our id to a callback."""

    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt override)
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except Exception:
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) == _HOTKEY_ID:
            self._on_hotkey()
        return False, 0


class GlobalHotkey(QObject):
    """Registers one system-wide hotkey and emits `activated` when pressed."""

    activated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.last_error: str | None = None
        self._registered = False
        self._filter = _HotkeyFilter(self.activated.emit)
        QGuiApplication_install(self._filter)

    def register(self, hotkey: Hotkey) -> bool:
        """Register `hotkey`. Returns False and sets `last_error` on failure."""
        self.unregister()

        modifiers, vk = hotkey.win32_args()
        # NOREPEAT stops auto-repeat from firing captures while held down.
        ok = bool(
            ctypes.windll.user32.RegisterHotKey(
                None, _HOTKEY_ID, modifiers | MOD_NOREPEAT, vk
            )
        )
        if not ok:
            err = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
            self.last_error = (
                f"RegisterHotKey failed for {hotkey.text} "
                f"(Win32 error {err}). Another program may already own it."
            )
            self._registered = False
            return False

        self.last_error = None
        self._registered = True
        return True

    def unregister(self) -> None:
        """Release the hotkey if one is held."""
        if self._registered:
            ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._registered = False


def QGuiApplication_install(event_filter: QAbstractNativeEventFilter) -> None:
    """Install a native event filter on the running QApplication.

    Split out so importing this module has no side effects beyond class
    definitions.
    """
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is None:
        raise RuntimeError("GlobalHotkey requires a QApplication to exist first")
    app.installNativeEventFilter(event_filter)
