"""System DPI detection.

Qt's own DPI-scaling support is deliberately disabled for this app (see
floatshot/__init__.py), because we need logical coordinates to equal
physical pixels so screen capture and mouse coordinates line up 1:1.
That means Qt cannot tell us the display scale -- we query Windows
directly and scale our own UI element sizes with it.
"""

from __future__ import annotations

from ctypes import windll

BASE_DPI = 96


def scale_from_dpi(dpi: int) -> float:
    """Convert a raw DPI value to a UI scale factor (96 DPI == 1.0)."""
    if dpi <= 0:
        return 1.0
    return dpi / BASE_DPI


def query_system_dpi() -> int:
    """Return the system DPI, falling back to 96 when unavailable."""
    try:
        dpi = int(windll.user32.GetDpiForSystem())
    except Exception:
        return BASE_DPI
    return dpi if dpi > 0 else BASE_DPI


def ui_scale() -> float:
    """The factor to multiply base UI pixel sizes by."""
    return scale_from_dpi(query_system_dpi())


def declare_dpi_awareness() -> str:
    """Tell Windows we handle DPI ourselves. Returns a status description.

    Without this, Windows bitmap-stretches the whole process on a scaled
    display: GetDpiForSystem() reports 96 and everything looks blurry.
    Python's own manifest already declares awareness, so in a source run
    this is usually a no-op -- but a PyInstaller-built exe uses its own
    bootloader manifest and may not declare it, which is why this stays.
    """
    try:
        ok = windll.user32.SetProcessDpiAwarenessContext(-4)  # PER_MONITOR_AWARE_V2
        return "ok" if ok else "already set by the host process"
    except AttributeError:
        pass
    except Exception as exc:  # pragma: no cover - depends on host OS
        return f"unexpected error: {exc}"

    try:
        windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return "ok (legacy API)"
    except Exception as exc:  # pragma: no cover - depends on host OS
        return f"failed: {exc}"
