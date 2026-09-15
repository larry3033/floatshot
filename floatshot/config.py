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
        "grip_px": 6,
        "min_width": 80,
        "min_height": 60,
    },
    "scale_mode": "free",
    "overlay": {
        "dim_alpha": 110,
        "border_color": "#4A9EFF",
        "border_width": 1,
        "show_size_hint": True,
    },
    "tray": {
        "show_startup_message": True,
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
