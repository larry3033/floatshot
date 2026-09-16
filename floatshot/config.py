"""Configuration loading with defaults merge and corruption recovery.

Pure Python -- no Qt import -- so it stays unit testable.

All tunable values live here. Nothing in the rest of the codebase should
hardcode a size, colour, or hotkey.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "hotkey": "Ctrl+Alt+Q",
    "shadow": {
        "padding": 18,
        "layers": 12,
        "max_alpha": 26,
        "offset_y": 3,
        "radius": 2,
        "color": "#000000",
        "falloff": 2.0,
    },
    "close_button": {
        "diameter_px": 16,
        "fade_ms": 120,
        "hover_opacity": 0.85,
        "hit_radius_factor": 1.5,
        "disc_color": "#282828",
        "disc_alpha": 200,
        "cross_color": "#FFFFFF",
        "cross_alpha": 235,
        "cross_arm_ratio": 0.38,
        "cross_stroke_ratio": 0.22,
    },
    "resize": {
        # Fraction of the window's width (for the left/right bands) and
        # height (for the top/bottom bands). A ratio rather than a pixel
        # count so the grab area grows with the picture: a fixed 6px band
        # is hard to catch on a large window and eats a small one whole.
        # Because the window size is already in physical pixels, a ratio
        # needs no DPI scaling of its own.
        "grip_ratio": 0.10,
        "min_width": 80,
        "min_height": 60,
    },
    # A coloured frame drawn just outside the picture, so a newly pasted
    # screenshot is obviously "there" instead of blending into whatever is
    # behind it.
    "outline": {
        "enabled": True,
        "color": "#FF0000",
        "width_px": 2,
        "offset_px": 0,
    },
    # Dots on the picture's four corners: they mark where the resize handles
    # are and read as "this is a window you can grab".
    "corner_dots": {
        "enabled": True,
        "color": "#00FF00",
        "diameter_px": 8,
    },
    "scale_mode": "free",
    "overlay": {
        "dim_color": "#000000",
        "dim_alpha": 110,
        "border_color": "#4A9EFF",
        "border_width": 1,
        "show_size_hint": True,
        "hint_font_px": 12,
        "hint_bg": "#000000",
        "hint_bg_alpha": 170,
        "hint_fg": "#FFFFFF",
        "hint_pad": 4,
        "hint_offset": 2,
        "hint_radius": 3,
    },
    "tray": {
        "show_startup_message": True,
    },
    # The tray glyph is drawn from these rather than from literals in
    # tray.py, so it is the one place its size and colours live.
    "icon": {
        "size": 64,
        "body_margin_left": 6,
        "body_margin_top": 16,
        "body_margin_right": 6,
        "body_margin_bottom": 8,
        "body_color": "#ECEFF1",
        "body_outline_color": "#37474F",
        "outline_px": 3,
        "corner_radius": 6,
        "lens_color": "#4A9EFF",
        "lens_diameter_px": 18,
    },
    # How hard the overlay insists on the keyboard after it is shown.
    # activateWindow() is SetForegroundWindow, which Windows may refuse
    # without error, and without the foreground the overlay never sees Esc.
    "activation": {
        "retry_ms": 250,
        "max_attempts": 8,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` on top of `base`, returning a new dict.

    Neither argument is mutated. When `override` supplies a non-dict where
    `base` had a dict, the override wins -- a malformed user value should be
    honoured (and later rejected by validation) rather than silently ignored.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    """A loaded config.json, merged over DEFAULTS."""

    def __init__(self, data: dict[str, Any], path: Path | None = None,
                 recovered: bool = False) -> None:
        self._data = data
        self._path = path
        self.recovered = recovered

    # -- construction ----------------------------------------------------

    @staticmethod
    def default_path() -> Path:
        """config.json next to the program, so it travels with the folder."""
        return Path(__file__).resolve().parent.parent / "config.json"

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Load config from `path`, creating or repairing it as needed.

        `recovered` is True when the file was absent, unreadable, or not a
        JSON object -- in which case the original is backed up to
        `<name>.bak` and replaced with defaults.
        """
        if not path.exists():
            cfg = cls(copy.deepcopy(DEFAULTS), path, recovered=True)
            cfg.save()
            return cfg

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level is not a JSON object")
        except Exception:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            cfg = cls(copy.deepcopy(DEFAULTS), path, recovered=True)
            cfg.save()
            return cfg

        return cls(deep_merge(DEFAULTS, raw), path, recovered=False)

    # -- access ----------------------------------------------------------

    @property
    def data(self) -> dict[str, Any]:
        """The live config dict. Mutating it directly bypasses nothing --
        call save() afterwards to persist."""
        return self._data

    def get(self, *keys: str, default: Any = None) -> Any:
        """Read a nested value: `cfg.get("shadow", "padding")`."""
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def set(self, *keys: str, value: Any) -> None:
        """Write a nested value, creating intermediate dicts as needed."""
        if not keys:
            raise ValueError("set() requires at least one key")
        node = self._data
        for key in keys[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                child = {}
                node[key] = child
            node = child
        node[keys[-1]] = value

    # -- persistence -----------------------------------------------------

    def save(self) -> None:
        """Write the config back to disk."""
        if self._path is None:
            raise RuntimeError("Config has no path; cannot save")
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
