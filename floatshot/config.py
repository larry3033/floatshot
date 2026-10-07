"""Configuration loading with defaults merge and corruption recovery.

Pure Python -- no Qt import -- so it stays unit testable.

All tunable values live here. Nothing in the rest of the codebase should
hardcode a size, colour, or hotkey.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
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
    # Capture-time conveniences, toggleable from the tray.
    "capture": {
        # QQ-style: put the freshly selected region on the clipboard as well
        # as opening the floating window. Off by default because it silently
        # clobbers whatever the user had copied.
        "copy_to_clipboard": False,
    },
    # Vision API used by the "AI 识别" window. Defaults point at DeepSeek's
    # OpenAI-compatible endpoint. The key is never read from opencode here --
    # put it in ai.api_key, or set the ai.api_key_env variable.
    "ai": {
        "format": "openai",          # openai | claude
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "api_key": "",
        "api_key_env": "FLOATSHOT_API_KEY",
        "timeout_s": 60,
        "max_tokens": 1024,
        "system_prompt": "你是一个图片理解助手。请根据用户的问题分析图片，"
                         "用简体中文回答，只给结论，不要客套。",
        "presets": [
            "描述这张图片的内容",
            "提取图中的所有文字",
            "把图中的文字翻译成中文",
            "解释图中报错或代码的含义",
        ],
    },
    # A coloured frame drawn just outside the picture, so a newly pasted
    # screenshot is obviously "there" instead of blending into whatever is
    # behind it. Mid-grey rather than black or white on purpose: a frame has
    # to stay visible against both a light and a dark desktop, and either
    # extreme disappears against one of them.
    "outline": {
        "enabled": True,
        "color": "#7A7A7A",
        "width_px": 2,
        "offset_px": 0,
    },
    # Dots on the picture's four corners: they mark where the resize handles
    # are and read as "this is a window you can grab". Lighter than the
    # frame so the two read as two levels rather than one thick border.
    "corner_dots": {
        "enabled": True,
        "color": "#C8C8C8",
        "diameter_px": 8,
    },
    # Styles for the annotation tools. Sizes here are in *image* pixels:
    # annotations live on the picture, not the window, so they do not get
    # multiplied by the DPI scale the way window chrome does.
    "annotation": {
        "stroke_color": "#FF3B30",
        "stroke_width": 2,
        "highlight_color": "#FFEB3B",
        "highlight_alpha": 90,
        "highlight_width": 16,
        "mosaic_block": 8,
        "mosaic_brush": 20,
        "text_color": "#FF3B30",
        "text_font_px": 18,
        "number_diameter_px": 24,
        "number_color": "#FF3B30",
        "number_text_color": "#FFFFFF",
        "number_font_px": 14,
    },
    # The pop-up annotation bar. Unlike the window chrome these sizes are
    # left in base pixels -- the bar sits beside the window, not inside the
    # picture, so it is not tied to the screenshot's own pixel grid.
    "toolbar": {
        "gap": 6,
        "background": "#FFFFFF",
        "border_color": "#D9D9D9",
        "radius": 10,
        "padding": 6,
        "spacing": 2,
        "button_size": 34,
        "icon_size": 20,
        "icon_color": "#333333",
        "hover_bg": "#EEEEEE",
        "active_bg": "#E1EEFF",
        "active_color": "#4A9EFF",
        "disabled_color": "#BDBDBD",
        "separator_color": "#E0E0E0",
    },
    # Colour swatches offered by the toolbar's palette button. Kept here so
    # the set of handy colours is editable without touching the code.
    "palette": {
        "colors": [
            "#FF3B30",
            "#FF9500",
            "#FFCC00",
            "#34C759",
            "#4A9EFF",
            "#AF52DE",
            "#000000",
            "#FFFFFF",
        ],
        "columns": 4,
        "swatch_size": 22,
        "spacing": 4,
        "padding": 8,
        "background": "#FFFFFF",
        "border_color": "#D9D9D9",
        "radius": 8,
    },
    # Stroke-thickness presets for the width button, same idea as the palette.
    "brush": {
        "widths": [2, 4, 6, 8, 12, 16],
        "preview_width": 34,
        "row_height": 22,
        "padding": 8,
        "spacing": 3,
        "background": "#FFFFFF",
        "border_color": "#D9D9D9",
        "radius": 8,
        "color": "#333333",
        "hover_bg": "#EEEEEE",
    },
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
        """config.json next to the program, so it travels with the folder.

        A frozen build must use the executable's own directory: __file__
        points into PyInstaller's temporary extraction folder, which is wiped
        when the process exits, so a config written there would not survive.
        """
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "config.json"
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
            cfg._save_quietly()
            return cfg

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level is not a JSON object")
        except Exception:
            # Recovery must never itself stop the app from starting. A path
            # that exists but cannot be read -- a directory, a locked file, a
            # permission-denied file -- fails the backup copy too, so both the
            # copy and the rewrite are best-effort.
            try:
                shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
            except Exception:
                pass
            cfg = cls(copy.deepcopy(DEFAULTS), path, recovered=True)
            cfg._save_quietly()
            return cfg

        return cls(deep_merge(DEFAULTS, raw), path, recovered=False)

    # -- access ----------------------------------------------------------

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

    def _save_quietly(self) -> None:
        """Persist best-effort: an unwritable location must not stop startup."""
        try:
            self.save()
        except Exception:
            pass
