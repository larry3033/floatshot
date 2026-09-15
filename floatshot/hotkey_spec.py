"""Parse hotkey strings such as "Ctrl+Alt+Q" into Win32 RegisterHotKey arguments.

Kept free of Qt and ctypes imports so it can be unit tested anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

# fsModifiers values accepted by RegisterHotKey.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

MODIFIER_ALIASES: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

NAMED_KEYS: dict[str, int] = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}

# Canonical display order, so parse_hotkey("Alt+Ctrl+Q").text is stable.
_MODIFIER_ORDER: tuple[tuple[int, str], ...] = (
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
)

# Canonical display names, keyed by virtual-key code.
#
# Built explicitly rather than by inverting NAMED_KEYS: that dict holds
# aliases ("del" and "delete" both map to 0x2E), so an inverted lookup
# would depend on insertion order and could render "Ctrl+del".
_CANONICAL_NAMES: dict[int, str] = {
    0x20: "Space",
    0x09: "Tab",
    0x0D: "Enter",
    0x1B: "Esc",
    0x08: "Backspace",
    0x2D: "Insert",
    0x2E: "Delete",
    0x24: "Home",
    0x23: "End",
    0x21: "PageUp",
    0x22: "PageDown",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    **{0x6F + i: f"F{i}" for i in range(1, 13)},
}


class HotkeyParseError(ValueError):
    """Raised when a hotkey string cannot be understood."""


@dataclass(frozen=True)
class Hotkey:
    """A parsed global hotkey."""

    modifiers: int
    vk: int
    text: str

    def win32_args(self) -> tuple[int, int]:
        """Return (fsModifiers, vk) ready for RegisterHotKey."""
        return self.modifiers, self.vk


def _resolve_key(part: str, spec: str) -> int:
    lower = part.lower()
    if lower in NAMED_KEYS:
        return NAMED_KEYS[lower]
    if len(part) == 1 and (part.isalpha() or part.isdigit()):
        return ord(part.upper())
    raise HotkeyParseError(
        f"unknown key {part!r} in hotkey {spec!r}; "
        f"expected A-Z, 0-9, F1-F12, or one of {sorted(NAMED_KEYS)}"
    )


def _describe_key(vk: int) -> str:
    if vk in _CANONICAL_NAMES:
        return _CANONICAL_NAMES[vk]
    return chr(vk)


def parse_hotkey(spec: str) -> Hotkey:
    """Parse a string like "Ctrl+Alt+Q" into a Hotkey.

    At least one modifier is required: registering a bare key as a global
    hotkey would swallow that key system-wide, which is never intended.
    """
    parts = [p.strip() for p in spec.split("+")]
    if not spec.strip() or any(p == "" for p in parts):
        raise HotkeyParseError(f"malformed hotkey {spec!r}: empty segment")

    modifiers = 0
    keys: list[int] = []

    for part in parts:
        lower = part.lower()
        if lower in MODIFIER_ALIASES:
            bit = MODIFIER_ALIASES[lower]
            if modifiers & bit:
                raise HotkeyParseError(f"duplicate modifier {part!r} in hotkey {spec!r}")
            modifiers |= bit
        else:
            keys.append(_resolve_key(part, spec))

    if not keys:
        raise HotkeyParseError(
            f"hotkey {spec!r} has no main key; a global hotkey needs at least "
            f"one modifier and one key"
        )
    if len(keys) > 1:
        raise HotkeyParseError(f"hotkey {spec!r} has more than one main key")
    if modifiers == 0:
        raise HotkeyParseError(
            f"hotkey {spec!r} has no modifier; registering a bare key globally "
            f"would swallow it system-wide"
        )

    names = [label for bit, label in _MODIFIER_ORDER if modifiers & bit]
    names.append(_describe_key(keys[0]))
    return Hotkey(modifiers=modifiers, vk=keys[0], text="+".join(names))
