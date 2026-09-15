# FloatShot 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Windows 截图贴图工具：按全局热键框选屏幕区域后，截图以置顶悬浮窗留存，可自由拖动、缩放、关闭。

**Architecture:** PySide6 无边框透明置顶窗口。进程启动时禁用 Qt 高 DPI 缩放，使逻辑坐标恒等于物理像素，抓屏与鼠标坐标 1:1 无需换算；UI 元素尺寸改由系统 DPI 手动补偿。抓屏采用「先抓后框」——按下热键立即抓取整个虚拟桌面到内存，再显示选区遮罩，避免把遮罩本身截进图片。

**Tech Stack:** Python 3.14 / PySide6 6.11 / ctypes 调 Win32（RegisterHotKey、GetDpiForSystem）/ pytest 9 / PyInstaller 6

**Spec:** `docs/superpowers/specs/2026-09-15-floatshot-design.md`

## Global Constraints

- **运行依赖只有 PySide6。** 不得引入 mss、Pillow、keyboard、pynput、pywin32。抓屏用 `QScreen.grabWindow`，图像用 Qt 自带类型。
- **所有可调数值走配置**，代码中只允许存在 `DEFAULTS` 兜底，不得出现硬编码的尺寸/颜色/热键常量。
- **`QT_ENABLE_HIGHDPI_SCALING=0` 与 `QT_SCALE_FACTOR=1` 必须在任何 `import PySide6` 之前设置**，且只能放在 `floatshot/__init__.py`。
- **所有 UI 尺寸 = 基准像素 × `ui_scale()` 后向上取整**（`math.ceil`），再经百分比 clamp 兜底。
- **仅支持 Windows。** 所有 Win32 调用需有失败回退，不得因 API 缺失而崩溃。
- 提交信息用 `feat:` / `test:` / `chore:` / `fix:` 前缀。

---

## 文件结构

```
openprogress/floatshot/                 ← git 仓库根
├── .gitignore
├── requirements.txt
├── pytest.ini
├── main.py                             入口
├── config.json                         运行时生成，已 gitignore
├── floatshot/
│   ├── __init__.py                     环境变量 + DPI 感知声明
│   ├── dpi.py                          系统 DPI 探测
│   ├── metrics.py                      UI 尺寸计算          纯函数
│   ├── geometry.py                     命中检测、比例约束     纯函数
│   ├── config.py                       配置加载/深合并/恢复    纯逻辑
│   ├── hotkey_spec.py                  热键字符串解析         纯函数
│   ├── hotkey.py                       Win32 全局热键
│   ├── capture.py                      虚拟桌面抓屏
│   ├── overlay.py                      全屏选区遮罩
│   ├── float_window.py                 悬浮窗本体
│   ├── tray.py                         托盘
│   └── app.py                          组装
└── tests/
    ├── test_dpi.py
    ├── test_metrics.py
    ├── test_geometry.py
    ├── test_config.py
    └── test_hotkey_spec.py
```

任务顺序按依赖排列：先做四个纯函数模块（可 TDD），再做 Win32/GUI 部分（需手动验证）。

---

### Task 1: 项目骨架与 git 初始化

**Files:**
- Create: `floatshot/.gitignore`
- Create: `floatshot/requirements.txt`
- Create: `floatshot/pytest.ini`
- Create: `floatshot/floatshot/__init__.py`
- Create: `floatshot/tests/` (目录)

**Interfaces:**
- Consumes: 无
- Produces: 可被 pytest 发现的包结构；`floatshot` 包可 import（`__init__.py` 暂为空，Task 6 填充）

- [ ] **Step 1: 初始化 git 仓库**

```bash
cd c:/Users/zibo9/Desktop/openprogress/floatshot
git init
```

- [ ] **Step 2: 写 `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
config.json
build/
dist/
```

`config.json` 忽略是有意的：它是运行时生成的用户配置，首次运行会自动重建。

`*.spec` **不**忽略——PyInstaller 生成的 spec 是构建配置的一部分，Task 12 要把它纳入版本控制。

- [ ] **Step 3: 写 `requirements.txt`**

```
PySide6>=6.5
```

仅此一行。全局约束要求运行依赖只有一个。

- [ ] **Step 4: 写 `pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
python_files = test_*.py
```

`pythonpath = .` 让 `tests/` 里的用例能直接 `import floatshot.xxx`。

- [ ] **Step 5: 创建包目录与空 `__init__.py`**

```bash
mkdir -p floatshot tests
touch floatshot/__init__.py
```

- [ ] **Step 6: 验证 pytest 能跑起来**

Run: `python -m pytest --collect-only`
Expected: 输出 `no tests ran`（0 tests collected），退出码 5。这是正确的——目录里还没有测试。

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt pytest.ini floatshot/__init__.py
git commit -m "chore: scaffold project skeleton"
```

---

### Task 2: 热键字符串解析（hotkey_spec.py）

**Files:**
- Create: `floatshot/hotkey_spec.py`
- Test: `tests/test_hotkey_spec.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `HotkeyParseError(ValueError)` —— 解析失败时抛出
  - `Hotkey` dataclass，字段 `modifiers: int`、`vk: int`、`text: str`
  - `parse_hotkey(spec: str) -> Hotkey`
  - 模块常量 `MOD_ALT/MOD_CONTROL/MOD_SHIFT/MOD_WIN/MOD_NOREPEAT`

**背景**：全局热键由 Win32 `RegisterHotKey(hwnd, id, fsModifiers, vk)` 注册，需要把配置里的 `"Ctrl+Alt+Q"` 转成 `(MOD_CONTROL|MOD_ALT, 0x51)`。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_hotkey_spec.py`：

```python
import pytest

from floatshot.hotkey_spec import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    Hotkey,
    HotkeyParseError,
    parse_hotkey,
)


def test_ctrl_alt_q():
    hk = parse_hotkey("Ctrl+Alt+Q")
    assert hk.modifiers == MOD_CONTROL | MOD_ALT
    assert hk.vk == 0x51  # ord('Q')
    assert hk.text == "Ctrl+Alt+Q"


def test_is_case_insensitive():
    assert parse_hotkey("ctrl+alt+q") == parse_hotkey("CTRL+ALT+Q")


def test_modifier_order_does_not_matter():
    assert parse_hotkey("Alt+Ctrl+Q") == parse_hotkey("Ctrl+Alt+Q")


def test_whitespace_is_tolerated():
    assert parse_hotkey(" Ctrl + Alt + Q ") == parse_hotkey("Ctrl+Alt+Q")


def test_all_four_modifiers():
    hk = parse_hotkey("Ctrl+Alt+Shift+Win+A")
    assert hk.modifiers == MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_WIN


def test_win_aliases():
    assert parse_hotkey("Super+A").modifiers == MOD_WIN
    assert parse_hotkey("Meta+A").modifiers == MOD_WIN


def test_digit_key():
    assert parse_hotkey("Ctrl+1").vk == 0x31


def test_function_keys():
    assert parse_hotkey("Ctrl+F1").vk == 0x70
    assert parse_hotkey("Ctrl+F12").vk == 0x7B


def test_named_keys():
    assert parse_hotkey("Ctrl+Space").vk == 0x20
    assert parse_hotkey("Ctrl+Delete").vk == 0x2E
    assert parse_hotkey("Ctrl+PageUp").vk == 0x21


def test_text_uses_canonical_key_names():
    # 别名要归一化成规范名，否则配置里写 "Ctrl+del" 会显示成 "Ctrl+del"
    assert parse_hotkey("Ctrl+del").text == "Ctrl+Delete"
    assert parse_hotkey("Ctrl+Escape").text == "Ctrl+Esc"
    assert parse_hotkey("Ctrl+return").text == "Ctrl+Enter"
    assert parse_hotkey("Ctrl+PageUp").text == "Ctrl+PageUp"


def test_text_modifier_order_is_canonical():
    # 无论输入顺序如何，显示顺序固定，便于日志与诊断信息阅读
    assert parse_hotkey("Shift+Alt+Ctrl+Q").text == "Ctrl+Alt+Shift+Q"


@pytest.mark.parametrize(
    "bad",
    [
        "",              # 空字符串
        "   ",           # 只有空白
        "Ctrl",          # 只有修饰键，没有主键
        "Q",             # 裸键：全局热键会霸占整个系统的该按键
        "Ctrl+Alt",      # 同上，缺主键
        "Ctrl+Foo",      # 未知键名
        "Ctrl+Alt+QQ",   # 多字符主键
        "Ctrl++",        # 空段
    ],
)
def test_rejects_invalid_specs(bad):
    with pytest.raises(HotkeyParseError):
        parse_hotkey(bad)


def test_rejects_duplicate_modifier():
    # Ctrl+Ctrl+Q 是配置错误，应当明确报错而非静默接受
    with pytest.raises(HotkeyParseError):
        parse_hotkey("Ctrl+Ctrl+Q")


def test_error_message_names_the_offending_spec():
    # match= 收到的是正则，"+ 必须转义"：未转义的 "Ctrl+Foo" 会被解析成
    # "Ctr" + "l"*(1..n) + "Foo"，永远匹配不到带加号的原始字符串。
    with pytest.raises(HotkeyParseError, match=r"Ctrl\+Foo"):
        parse_hotkey("Ctrl+Foo")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_hotkey_spec.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'floatshot.hotkey_spec'`

- [ ] **Step 3: 实现 `floatshot/hotkey_spec.py`**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_hotkey_spec.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 快速人工确认解析结果**

Run:
```bash
python -c "from floatshot.hotkey_spec import parse_hotkey; h=parse_hotkey('Ctrl+Alt+Q'); print(h, h.win32_args())"
```
Expected: `Hotkey(modifiers=3, vk=81, text='Ctrl+Alt+Q') (3, 81)`。`3` 即 `MOD_CONTROL|MOD_ALT`。

- [ ] **Step 6: Commit**

```bash
git add floatshot/hotkey_spec.py tests/test_hotkey_spec.py
git commit -m "feat: parse hotkey strings into Win32 key codes"
```

---

### Task 3: 配置层（config.py）

**Files:**
- Create: `floatshot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `DEFAULTS: dict` —— 全部默认值
  - `deep_merge(base: dict, override: dict) -> dict` —— 纯函数，不修改入参
  - `Config` 类：`Config.load(path: Path) -> Config`、`.get(*keys)`、`.set(*keys, value=...)`、`.save()`、`.data` 属性、`.recovered: bool` 属性

**背景**：配置要能承受分发场景——用户拿到新版本后，旧 `config.json` 缺新键不能崩；文件损坏也不能阻断启动。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_config.py`：

```python
import json
from pathlib import Path

import pytest

from floatshot.config import DEFAULTS, Config, deep_merge


# ---------- deep_merge ----------

def test_deep_merge_overrides_scalar():
    assert deep_merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_deep_merge_keeps_missing_keys():
    assert deep_merge({"a": 1, "b": 2}, {"a": 9}) == {"a": 9, "b": 2}


def test_deep_merge_recurses_into_nested_dicts():
    base = {"shadow": {"padding": 18, "layers": 12}}
    override = {"shadow": {"padding": 30}}
    assert deep_merge(base, override) == {"shadow": {"padding": 30, "layers": 12}}


def test_deep_merge_does_not_mutate_arguments():
    base = {"shadow": {"padding": 18}}
    override = {"shadow": {"padding": 30}}
    deep_merge(base, override)
    assert base == {"shadow": {"padding": 18}}


def test_deep_merge_replaces_dict_with_scalar():
    # 用户把嵌套节写成标量是配置错误，应以用户值为准而非崩溃
    assert deep_merge({"a": {"b": 1}}, {"a": 5}) == {"a": 5}


# ---------- Config.load ----------

def test_load_creates_file_when_missing(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    assert cfg.recovered is True
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULTS


def test_load_reads_existing_values(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "Ctrl+Shift+X"}), encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.get("hotkey") == "Ctrl+Shift+X"
    assert cfg.recovered is False


def test_load_fills_missing_keys_from_defaults(tmp_path: Path):
    # 模拟旧版本配置文件缺少新版本才引入的键
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "Ctrl+Shift+X"}), encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.get("shadow", "padding") == DEFAULTS["shadow"]["padding"]


def test_load_recovers_from_corrupt_json(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.recovered is True
    assert cfg.get("hotkey") == DEFAULTS["hotkey"]
    assert (tmp_path / "config.json.bak").exists()
    # 损坏文件已被替换为可解析的默认值
    assert json.loads(path.read_text(encoding="utf-8")) == DEFAULTS


def test_load_recovers_from_non_dict_json(tmp_path: Path):
    # 顶层是数组或标量同样属于损坏
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    cfg = Config.load(path)
    assert cfg.recovered is True


# ---------- get / set / save ----------

def test_get_returns_default_when_key_absent(tmp_path: Path):
    cfg = Config.load(tmp_path / "config.json")
    assert cfg.get("nope", "nothing", default="fallback") == "fallback"


def test_set_then_save_round_trips(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    cfg.set("hotkey", value="Ctrl+Shift+Z")
    cfg.save()

    reloaded = Config.load(path)
    assert reloaded.get("hotkey") == "Ctrl+Shift+Z"


def test_set_preserves_sibling_keys(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    cfg.set("shadow", "padding", value=40)
    cfg.save()

    reloaded = Config.load(path)
    assert reloaded.get("shadow", "padding") == 40
    assert reloaded.get("shadow", "layers") == DEFAULTS["shadow"]["layers"]


def test_save_writes_utf8_and_indent(tmp_path: Path):
    path = tmp_path / "config.json"
    cfg = Config.load(path)
    cfg.save()
    raw = path.read_text(encoding="utf-8")
    assert "\n" in raw  # 缩进过，便于手工编辑


def test_default_config_is_not_shared_between_instances(tmp_path: Path):
    # 深拷贝保护：改一个实例不能污染 DEFAULTS
    a = Config.load(tmp_path / "a.json")
    a.set("shadow", "padding", value=99)
    assert DEFAULTS["shadow"]["padding"] != 99
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'floatshot.config'`

- [ ] **Step 3: 实现 `floatshot/config.py`**

```python
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
    },
    "close_button": {
        "diameter_px": 16,
        "fade_ms": 120,
        "hover_opacity": 0.85,
        "hit_radius_factor": 1.5,
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add floatshot/config.py tests/test_config.py
git commit -m "feat: config layer with defaults merge and corruption recovery"
```

---

### Task 4: UI 尺寸计算（metrics.py）

**Files:**
- Create: `floatshot/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Metrics` frozen dataclass，字段 `padding: int`、`grip: int`、`close_diameter: int`、`close_hit_radius: float`
  - `compute_metrics(scale: float, width: int, height: int, *, shadow_padding: int, grip_px: int, close_diameter_px: int, close_hit_factor: float = 0.75) -> Metrics`

**背景**：这是 spec §2.2 的三层策略的落点。判定区必须随 DPI 放大（否则高分屏点不中），但必须有百分比上限（否则小窗口下四角判定区重叠、按钮占满画面）。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_metrics.py`：

```python
import pytest

from floatshot.metrics import Metrics, compute_metrics


def _m(scale=1.0, w=400, h=300, pad=18, grip=6, close=16, hit=1.5):
    return compute_metrics(
        scale=scale, width=w, height=h,
        shadow_padding=pad, grip_px=grip,
        close_diameter_px=close, close_hit_radius_factor=hit,
    )


# ---------- 主规则：固定基准 × DPI ----------

def test_100_percent_scale_is_identity():
    m = _m(scale=1.0)
    assert m.grip == 6
    assert m.close_diameter == 16
    assert m.padding == 18


def test_125_percent_scale_rounds_up():
    # 6 * 1.25 = 7.5 -> ceil -> 8；判定区宁大勿小
    m = _m(scale=1.25)
    assert m.grip == 8
    assert m.close_diameter == 20   # 16 * 1.25 = 20 恰好整数


def test_150_percent_scale():
    m = _m(scale=1.5)
    assert m.grip == 9              # 6 * 1.5 = 9
    assert m.close_diameter == 24   # 16 * 1.5 = 24
    assert m.padding == 27          # 18 * 1.5 = 27


def test_hit_radius_exceeds_visual_radius():
    # 判定区必须大于视觉尺寸，否则边缘像素点不中
    for scale in (1.0, 1.25, 1.5, 2.0):
        m = _m(scale=scale)
        assert m.close_hit_radius > m.close_diameter / 2


def test_hit_radius_scales_with_visual_size():
    # 16px 按钮 -> 视觉半径 8，判定半径 8 * 1.5 = 12
    assert _m(scale=1.0).close_hit_radius == pytest.approx(12.0)
    # 24px 按钮 -> 视觉半径 12，判定半径 18
    assert _m(scale=1.5).close_hit_radius == pytest.approx(18.0)


# ---------- 兜底：百分比 clamp ----------

def test_grip_clamped_on_tiny_window():
    # min(400,300)/3 = 100，正常不触发；窗口缩到 60x60 时 grip 应被压到 20
    m = _m(w=60, h=60, grip=100)
    assert m.grip == 20             # 60/3


def test_grip_never_exceeds_one_third_of_short_side():
    m = _m(w=90, h=400, scale=2.0, grip=50)
    assert m.grip <= 90 // 3


def test_close_button_clamped_on_tiny_window():
    # min(60,60)*0.3 = 18
    m = _m(w=60, h=60, scale=2.0, close=100)
    assert m.close_diameter == 18


def test_clamp_does_not_trigger_on_normal_window():
    m = _m(w=400, h=300, scale=1.0)
    assert m.grip == 6
    assert m.close_diameter == 16


# ---------- 边界 ----------

def test_degenerate_window_still_returns_positive_grip():
    # 窗口尺寸为 0 或负数不应产生负判定区
    m = _m(w=0, h=0)
    assert m.grip >= 1
    assert m.close_diameter >= 1


def test_result_is_frozen():
    m = _m()
    with pytest.raises(Exception):
        m.grip = 99


def test_returns_metrics_instance():
    assert isinstance(_m(), Metrics)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'floatshot.metrics'`

- [ ] **Step 3: 实现 `floatshot/metrics.py`**

```python
"""Compute DPI-scaled UI element sizes for a window of a given size.

Pure functions -- no Qt import -- so the clamping behaviour at extreme
window sizes can be unit tested rather than eyeballed on screen.

Three-layer strategy (see spec section 2.2):
  1. Base pixel size x DPI scale, rounded up. Keeps the feel identical
     across 100% / 125% / 150% displays.
  2. Percentage clamp. Stops corner grips from overlapping on tiny
     windows and stops the close button from eating the whole picture.
  3. Hit areas stay larger than visual sizes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Metrics:
    """DPI-adjusted element sizes for one window size."""

    padding: int
    grip: int
    close_diameter: int
    close_hit_radius: float


def _scaled(base_px: int, scale: float) -> int:
    """Scale a base pixel value, rounding up and never dropping below 1."""
    return max(1, math.ceil(base_px * scale))


def compute_metrics(
    scale: float,
    width: int,
    height: int,
    *,
    shadow_padding: int,
    grip_px: int,
    close_diameter_px: int,
    close_hit_radius_factor: float = 1.5,
) -> Metrics:
    """Return element sizes for a window of `width` x `height` physical pixels.

    `scale` is the system UI scale (1.0 == 96 DPI).
    `close_hit_radius_factor` is how much larger the clickable radius is
    than the drawn radius; a hit area smaller than the visual button would
    make edge pixels unclickable.
    """
    short_side = max(0, min(width, height))

    grip = _scaled(grip_px, scale)
    # Layer 2: keep the four corner grips from overlapping each other.
    grip = max(1, min(grip, short_side // 3)) if short_side else grip

    close_diameter = _scaled(close_diameter_px, scale)
    # Layer 2: keep the button from swallowing a very small window.
    if short_side:
        close_diameter = max(1, min(close_diameter, int(short_side * 0.3)))

    return Metrics(
        padding=_scaled(shadow_padding, scale),
        grip=grip,
        close_diameter=close_diameter,
        close_hit_radius=(close_diameter / 2.0) * max(1.0, close_hit_radius_factor),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add floatshot/metrics.py tests/test_metrics.py
git commit -m "feat: DPI-scaled UI metrics with percentage clamping"
```

---

### Task 5: 命中检测与比例约束（geometry.py）

**Files:**
- Create: `floatshot/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Edge(IntFlag)`，成员 `NONE=0, LEFT=1, RIGHT=2, TOP=4, BOTTOM=8`
  - `hit_test(x: float, y: float, width: int, height: int, grip: int) -> Edge`
  - `fit_aspect_width(orig_w: int, orig_h: int, target_w: int) -> tuple[int, int]`
  - `fit_aspect_height(orig_w: int, orig_h: int, target_h: int) -> tuple[int, int]`
  - `fit_aspect_corner(orig_w: int, orig_h: int, cand_w: int, cand_h: int) -> tuple[int, int]`
  - `apply_resize(start: tuple[int,int,int,int], edge: Edge, dx: int, dy: int, *, min_w: int, min_h: int) -> tuple[int,int,int,int]`

**背景**：拖拽缩放是这类程序最容易出 bug 的地方。抽成纯函数后可以断言各种边界，不用拿鼠标在屏幕上试。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_geometry.py`：

```python
import pytest

from floatshot.geometry import (
    Edge,
    apply_resize,
    fit_aspect_corner,
    fit_aspect_height,
    fit_aspect_width,
    hit_test,
)


# ---------- hit_test ----------

W, H, G = 400, 300, 6


def test_center_is_not_an_edge():
    assert hit_test(200, 150, W, H, G) == Edge.NONE


def test_left_edge():
    assert hit_test(2, 150, W, H, G) == Edge.LEFT


def test_right_edge():
    assert hit_test(W - 2, 150, W, H, G) == Edge.RIGHT


def test_top_edge():
    assert hit_test(200, 2, W, H, G) == Edge.TOP


def test_bottom_edge():
    assert hit_test(200, H - 2, W, H, G) == Edge.BOTTOM


def test_corners_are_combinations():
    assert hit_test(2, 2, W, H, G) == Edge.LEFT | Edge.TOP
    assert hit_test(W - 2, 2, W, H, G) == Edge.RIGHT | Edge.TOP
    assert hit_test(2, H - 2, W, H, G) == Edge.LEFT | Edge.BOTTOM
    assert hit_test(W - 2, H - 2, W, H, G) == Edge.RIGHT | Edge.BOTTOM


def test_grip_boundary_is_inclusive_at_zero():
    assert hit_test(0, 150, W, H, G) == Edge.LEFT


def test_grip_boundary_is_exclusive_at_grip():
    # 恰好等于 grip 时已经在内容区内，不应命中
    assert hit_test(G, 150, W, H, G) == Edge.NONE


def test_just_inside_grip_hits():
    assert hit_test(G - 1, 150, W, H, G) == Edge.LEFT


def test_oversized_grip_is_clamped_internally():
    # 防御性：调用方传了未经 clamp 的 grip，也不能让左右判定区重叠
    # 90x90 的窗口，grip=100 被内部压到 30；点 (50,50) 落在中间安全区
    assert hit_test(50, 50, 90, 90, grip=100) == Edge.NONE


def test_clamped_grip_still_matches_its_boundary():
    # 承上：clamp 到 30 之后，29 仍应命中左边缘，30 应落回内容区
    assert hit_test(29, 50, 90, 90, grip=100) == Edge.LEFT
    assert hit_test(30, 50, 90, 90, grip=100) == Edge.NONE


def test_negative_coordinates_are_outside():
    assert hit_test(-5, 150, W, H, G) == Edge.NONE


def test_point_beyond_window_is_outside():
    assert hit_test(W + 5, 150, W, H, G) == Edge.NONE


# ---------- 比例约束 ----------

def test_fit_aspect_width_keeps_ratio():
    assert fit_aspect_width(200, 100, 400) == (400, 200)


def test_fit_aspect_height_keeps_ratio():
    assert fit_aspect_height(200, 100, 300) == (600, 300)


def test_fit_aspect_rounds_to_int():
    w, h = fit_aspect_width(300, 200, 100)      # 100 * 200/300 = 66.67
    assert isinstance(w, int) and isinstance(h, int)
    assert h in (66, 67)


def test_fit_aspect_corner_picks_dominant_axis():
    # 宽变化比例更大 -> 以宽为准
    assert fit_aspect_corner(200, 100, 600, 110) == (600, 300)
    # 高变化比例更大 -> 以高为准
    assert fit_aspect_corner(200, 100, 210, 500) == (1000, 500)


def test_fit_aspect_never_returns_zero():
    w, h = fit_aspect_width(1000, 1000, 1)
    assert w >= 1 and h >= 1


# ---------- apply_resize ----------

START = (100, 100, 400, 300)   # x, y, w, h


def test_resize_right_edge_grows_width_only():
    assert apply_resize(START, Edge.RIGHT, dx=50, dy=0, min_w=80, min_h=60) == (100, 100, 450, 300)


def test_resize_bottom_edge_grows_height_only():
    assert apply_resize(START, Edge.BOTTOM, dx=0, dy=40, min_w=80, min_h=60) == (100, 100, 400, 340)


def test_resize_left_edge_moves_origin():
    # 拖左边：原点左移、宽度增加，右边界不动
    assert apply_resize(START, Edge.LEFT, dx=-50, dy=0, min_w=80, min_h=60) == (50, 100, 450, 300)


def test_resize_top_edge_moves_origin():
    assert apply_resize(START, Edge.TOP, dx=0, dy=-30, min_w=80, min_h=60) == (100, 70, 400, 330)


def test_resize_bottom_right_corner():
    assert apply_resize(START, Edge.RIGHT | Edge.BOTTOM, dx=20, dy=30, min_w=80, min_h=60) == (100, 100, 420, 330)


def test_resize_top_left_corner():
    assert apply_resize(START, Edge.LEFT | Edge.TOP, dx=-20, dy=-30, min_w=80, min_h=60) == (80, 70, 420, 330)


def test_min_width_is_enforced():
    _, _, w, _ = apply_resize(START, Edge.RIGHT, dx=-1000, dy=0, min_w=80, min_h=60)
    assert w == 80


def test_min_height_is_enforced():
    _, _, _, h = apply_resize(START, Edge.BOTTOM, dx=0, dy=-1000, min_w=80, min_h=60)
    assert h == 60


def test_min_width_keeps_right_edge_anchored_when_dragging_left():
    # 拖左边到极限：右边界必须保持不动，不能把窗口推走
    x, _, w, _ = apply_resize(START, Edge.LEFT, dx=1000, dy=0, min_w=80, min_h=60)
    assert x + w == START[0] + START[2]


def test_min_height_keeps_bottom_edge_anchored_when_dragging_top():
    _, y, _, h = apply_resize(START, Edge.TOP, dx=0, dy=1000, min_w=80, min_h=60)
    assert y + h == START[1] + START[3]


def test_edge_none_returns_start_unchanged():
    assert apply_resize(START, Edge.NONE, dx=10, dy=10, min_w=80, min_h=60) == START
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_geometry.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'floatshot.geometry'`

- [ ] **Step 3: 实现 `floatshot/geometry.py`**

```python
"""Window edge hit-testing and resize math.

Pure functions -- no Qt import -- so the fiddly boundary behaviour can be
unit tested instead of hunted down with a mouse.
"""

from __future__ import annotations

from enum import IntFlag


class Edge(IntFlag):
    """Which window edges a point is touching. Corners are combinations."""

    NONE = 0
    LEFT = 1
    RIGHT = 2
    TOP = 4
    BOTTOM = 8


def hit_test(x: float, y: float, width: int, height: int, grip: int) -> Edge:
    """Return the edges touched by the client-area point (x, y).

    `grip` is the thickness of the resize band along each edge. It is
    clamped internally so that an oversized value can never make opposite
    bands overlap and swallow the whole window.
    """
    if width <= 0 or height <= 0:
        return Edge.NONE

    grip = max(1, min(grip, min(width, height) // 3))

    if not (0 <= x < width and 0 <= y < height):
        return Edge.NONE

    edge = Edge.NONE
    if x < grip:
        edge |= Edge.LEFT
    elif x >= width - grip:
        edge |= Edge.RIGHT
    if y < grip:
        edge |= Edge.TOP
    elif y >= height - grip:
        edge |= Edge.BOTTOM
    return edge


def fit_aspect_width(orig_w: int, orig_h: int, target_w: int) -> tuple[int, int]:
    """Size the image to `target_w` wide, keeping its aspect ratio."""
    if orig_w <= 0 or orig_h <= 0:
        return max(1, target_w), max(1, target_w)
    w = max(1, int(target_w))
    h = max(1, round(w * orig_h / orig_w))
    return w, h


def fit_aspect_height(orig_w: int, orig_h: int, target_h: int) -> tuple[int, int]:
    """Size the image to `target_h` tall, keeping its aspect ratio."""
    if orig_w <= 0 or orig_h <= 0:
        return max(1, target_h), max(1, target_h)
    h = max(1, int(target_h))
    w = max(1, round(h * orig_w / orig_h))
    return w, h


def fit_aspect_corner(
    orig_w: int, orig_h: int, cand_w: int, cand_h: int
) -> tuple[int, int]:
    """Lock a corner drag to the image aspect ratio.

    Whichever axis changed proportionally more wins, so dragging a corner
    does not jitter between the two constraints.
    """
    if orig_w <= 0 or orig_h <= 0:
        return max(1, cand_w), max(1, cand_h)
    ratio_w = max(1, cand_w) / orig_w
    ratio_h = max(1, cand_h) / orig_h
    if ratio_w >= ratio_h:
        return fit_aspect_width(orig_w, orig_h, cand_w)
    return fit_aspect_height(orig_w, orig_h, cand_h)


def apply_resize(
    start: tuple[int, int, int, int],
    edge: Edge,
    dx: int,
    dy: int,
    *,
    min_w: int,
    min_h: int,
) -> tuple[int, int, int, int]:
    """Apply a resize drag to `start` = (x, y, w, h).

    Edges not present in `edge` are immovable: dragging the left edge
    changes x and w but leaves the right edge exactly where it was, which
    is what stops the window from sliding when it hits the minimum size.
    """
    x, y, w, h = start
    if edge == Edge.NONE:
        return start

    if Edge.LEFT in edge:
        new_w = max(min_w, w - dx)
        x = x + (w - new_w)
        w = new_w
    elif Edge.RIGHT in edge:
        w = max(min_w, w + dx)

    if Edge.TOP in edge:
        new_h = max(min_h, h - dy)
        y = y + (h - new_h)
        h = new_h
    elif Edge.BOTTOM in edge:
        h = max(min_h, h + dy)

    return x, y, w, h
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_geometry.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add floatshot/geometry.py tests/test_geometry.py
git commit -m "feat: edge hit-testing and resize math"
```

---

### Task 6: DPI 探测与包初始化（dpi.py + __init__.py）

**Files:**
- Create: `floatshot/dpi.py`
- Modify: `floatshot/__init__.py`（Task 1 创建时为空）
- Test: `tests/test_dpi.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `scale_from_dpi(dpi: int) -> float`
  - `query_system_dpi() -> int`
  - `ui_scale() -> float`
  - `declare_dpi_awareness() -> str` —— 返回描述声明结果的字符串，供诊断显示

**背景**：这是 spec §2.3。进程必须声明 DPI 感知，否则 Windows 会位图拉伸整个程序，`GetDpiForSystem()` 恒返回 96。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_dpi.py`：

```python
import pytest

from floatshot.dpi import scale_from_dpi, ui_scale


@pytest.mark.parametrize(
    "dpi,expected",
    [(96, 1.0), (120, 1.25), (144, 1.5), (192, 2.0)],
)
def test_scale_from_dpi(dpi, expected):
    assert scale_from_dpi(dpi) == pytest.approx(expected)


def test_scale_from_zero_falls_back_to_1():
    # 某些虚拟显示驱动会返回 0，不能让它变成除零或 0 尺寸
    assert scale_from_dpi(0) == 1.0


def test_scale_from_negative_falls_back_to_1():
    assert scale_from_dpi(-96) == 1.0


def test_ui_scale_is_positive():
    assert ui_scale() > 0


def test_ui_scale_tracks_query_system_dpi(monkeypatch):
    import floatshot.dpi as dpi_mod

    monkeypatch.setattr(dpi_mod, "query_system_dpi", lambda: 144)
    assert ui_scale() == pytest.approx(1.5)


def test_query_system_dpi_returns_sane_value_on_windows():
    from floatshot.dpi import query_system_dpi

    dpi = query_system_dpi()
    assert 48 <= dpi <= 960, f"implausible DPI {dpi}"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_dpi.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'floatshot.dpi'`

- [ ] **Step 3: 实现 `floatshot/dpi.py`**

```python
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
```

- [ ] **Step 4: 写 `floatshot/__init__.py`**

```python
"""FloatShot -- screenshot to floating window.

The environment variables and the DPI-awareness call below MUST run before
Qt is imported. Qt reads these settings once, at first import, and silently
ignores later changes -- a mistake here would not crash, it would just make
captures land on the wrong pixels on a scaled display, which is invisible
on a 100% display.

Living in __init__.py rather than main.py is deliberate: every import path
into this package runs this file first, so no entry point can bypass it.

Disabling Qt's scaling means logical coordinates equal physical pixels, so
capture and mouse coordinates line up with no conversion. The cost is that
Qt widgets no longer grow on high-DPI displays; UI element sizes are scaled
manually instead, via floatshot.dpi.ui_scale().
"""

import os

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

from . import dpi  # noqa: E402  -- must follow the env vars above

# Kept rather than discarded: the tray's diagnostics panel reports this,
# which is how a packaged build gets checked for DPI awareness.
DPI_AWARENESS_STATUS = dpi.declare_dpi_awareness()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_dpi.py -v`
Expected: 全部 PASS

- [ ] **Step 6: 人工确认当前 DPI 探测正确**

Run:
```bash
python -c "from floatshot.dpi import ui_scale, query_system_dpi, declare_dpi_awareness; print('dpi', query_system_dpi(), 'scale', ui_scale())"
```
Expected: 在 100% 缩放下输出 `dpi 96 scale 1.0`。若这里显示 96 但你的显示设置是 125%，说明 DPI 感知没生效——记录该现象，但先继续；最终的判断依据是 Task 11 的托盘诊断信息。

- [ ] **Step 7: Commit**

```bash
git add floatshot/dpi.py floatshot/__init__.py tests/test_dpi.py
git commit -m "feat: system DPI detection and package init"
```

---

### Task 7: 虚拟桌面抓屏（capture.py）

**Files:**
- Create: `floatshot/capture.py`

**Interfaces:**
- Consumes: `floatshot.dpi`
- Produces:
  - `virtual_geometry() -> QRect` —— 所有屏幕的并集，可能含负坐标
  - `grab_virtual_desktop() -> tuple[QPixmap, QRect]` —— 返回 (整幅截图, 虚拟桌面矩形)
  - `crop(pixmap: QPixmap, region: QRect, origin: QRect) -> QPixmap`

**背景**：多屏时 `QScreen.grabWindow(0)` 只抓单个屏幕，需要逐屏抓取再拼接到一张画布上。`origin` 是虚拟桌面矩形，用于把窗口坐标转成画布坐标。

- [ ] **Step 1: 实现 `floatshot/capture.py`**

```python
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
```

- [ ] **Step 2: 写一个一次性验证脚本并运行**

Run:

```bash
python -c "
from PySide6.QtWidgets import QApplication
import floatshot
from floatshot.capture import grab_virtual_desktop, virtual_geometry
app = QApplication([])
geo = virtual_geometry()
pm, origin = grab_virtual_desktop()
print('virtual geometry :', geo)
print('origin           :', origin)
print('canvas size      :', pm.width(), 'x', pm.height())
assert not pm.isNull(), 'capture returned a null pixmap'
assert pm.width() == geo.width() and pm.height() == geo.height()
print('OK')
"
```
Expected: 打印出虚拟桌面矩形与画布尺寸，两者一致，最后输出 `OK`。若 assertion 失败，说明某块屏幕抓取返回空——在多屏环境下检查。

- [ ] **Step 3: 人工检查抓到的图确实有内容**

Run:

```bash
python -c "
from PySide6.QtWidgets import QApplication
import floatshot
from floatshot.capture import grab_virtual_desktop
app = QApplication([])
pm, _ = grab_virtual_desktop()
pm.save('capture_probe.png')
img = pm.toImage()
# 采样若干点，确认不是全黑
colors = {img.pixel(x, y) for x in range(0, img.width(), 200) for y in range(0, img.height(), 200)}
assert len(colors) > 1, 'canvas looks uniformly blank -- capture failed'
print('distinct sampled colours:', len(colors), '-> OK')
"
```
Expected: `distinct sampled colours: <大于1> -> OK`。然后**打开 `capture_probe.png` 用眼睛确认**它就是你当前的桌面截图。确认后删除该文件。

- [ ] **Step 4: Commit**

```bash
git add floatshot/capture.py
git commit -m "feat: virtual desktop capture"
```

---

### Task 8: 全局热键（hotkey.py）

**Files:**
- Create: `floatshot/hotkey.py`

**Interfaces:**
- Consumes: `floatshot.hotkey_spec.Hotkey`, `floatshot.hotkey_spec.parse_hotkey`, `floatshot.hotkey_spec.MOD_NOREPEAT`
- Produces:
  - `GlobalHotkey(QObject)` 类
    - 信号 `activated`（无参数）
    - `register(hotkey: Hotkey) -> bool`
    - `unregister() -> None`
    - 属性 `last_error: str | None`

**背景**：`RegisterHotKey(hwnd=None, ...)` 把热键绑定到调用线程的消息队列，`WM_HOTKEY` 通过 `QAbstractNativeEventFilter` 捕获。⚠ 这是本计划中唯一**必须实测确认**的技术点：若线程消息收不到，改用隐藏窗口方案（见 Step 5）。

- [ ] **Step 1: 实现 `floatshot/hotkey.py`**

```python
"""System-wide hotkey registration via Win32 RegisterHotKey.

Registering with hwnd=NULL binds the hotkey to this thread's message
queue; WM_HOTKEY then arrives through Qt's native event filter.
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
```

- [ ] **Step 2: 写一个一次性验证脚本并运行**

Run:

```bash
python -c "
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import floatshot
from floatshot.hotkey import GlobalHotkey
from floatshot.hotkey_spec import parse_hotkey

app = QApplication([])
hk = GlobalHotkey()
ok = hk.register(parse_hotkey('Ctrl+Alt+Q'))
print('register ->', ok, '|', hk.last_error)

fired = []
hk.activated.connect(lambda: (fired.append(1), print('HOTKEY FIRED'), app.quit()))

print('>>> 请在 5 秒内按下 Ctrl+Alt+Q <<<')
QTimer.singleShot(5000, app.quit)
app.exec()
hk.unregister()
print('RESULT:', 'PASS' if fired else 'NO TRIGGER')
"
```
Expected: 提示后 5 秒内按下 `Ctrl+Alt+Q`，应打印 `HOTKEY FIRED` 与 `RESULT: PASS`。

- [ ] **Step 3: 判断结果并分支**

- **若显示 PASS** —— 线程消息方案成立，继续 Step 4。
- **若显示 NO TRIGGER** —— 说明 `QAbstractNativeEventFilter` 收不到 `hwnd=NULL` 的线程消息。改用隐藏接收窗口方案：在 `GlobalHotkey.__init__` 中创建一个 `QWidget`，`self._hwnd = int(widget.winId())`，把 `RegisterHotKey(None, ...)` 与 `UnregisterHotKey(None, ...)` 的第一个参数从 `None` 换成 `self._hwnd`，然后重跑 Step 2 确认 PASS。把最终采用的方式写进模块 docstring。

- [ ] **Step 4: 确认重复注册不会泄漏**

Run:

```bash
python -c "
from PySide6.QtWidgets import QApplication
import floatshot
from floatshot.hotkey import GlobalHotkey
from floatshot.hotkey_spec import parse_hotkey
app = QApplication([])
hk = GlobalHotkey()
for i in range(3):
    print(i, hk.register(parse_hotkey('Ctrl+Alt+Q')))
hk.unregister()
print('OK')
"
```
Expected: 三次都打印 `True`（`register` 会先 `unregister`），最后 `OK`。若第二次起返回 `False`，说明 `unregister` 没生效。

- [ ] **Step 5: Commit**

```bash
git add floatshot/hotkey.py
git commit -m "feat: global hotkey via RegisterHotKey"
```

---

### Task 9: 悬浮窗（float_window.py）

**Files:**
- Create: `floatshot/float_window.py`

**Interfaces:**
- Consumes: `floatshot.config.Config`、`floatshot.metrics`、`floatshot.geometry`、`floatshot.dpi.ui_scale`
- Produces:
  - `FloatWindow(QWidget)` 类
    - 构造 `FloatWindow(pixmap: QPixmap, config: Config, scale: float | None = None)`
    - 信号 `closed = Signal(object)` —— 携带自身，供 app 从列表移除
    - 方法 `image_rect() -> QRect`、`close_button_center() -> QPointF`

**背景**：这是视觉主体。阴影手绘而非用 `QGraphicsDropShadowEffect`（spec §5.3）。关闭按钮悬停淡入（spec §5.4）。缩放分自由/Shift 等比两种（spec §5.5）。

- [ ] **Step 1: 实现 `floatshot/float_window.py`**

```python
"""The floating screenshot window.

Frameless, translucent, always on top, with a hand-painted soft shadow and
a circular close button that fades in on hover.

The shadow is painted rather than done with QGraphicsDropShadowEffect:
that effect is unreliable on Windows for translucent frameless top-level
windows, and it applies to the whole widget tree, which would put a shadow
behind the close button too.
"""

from __future__ import annotations

import math

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .config import Config
from .dpi import ui_scale
from .geometry import (
    Edge,
    apply_resize,
    fit_aspect_corner,
    fit_aspect_width,
    fit_aspect_height,
    hit_test,
)
from .metrics import Metrics, compute_metrics

# Cursor shape per edge combination.
_CURSORS: dict[Edge, Qt.CursorShape] = {
    Edge.LEFT: Qt.CursorShape.SizeHorCursor,
    Edge.RIGHT: Qt.CursorShape.SizeHorCursor,
    Edge.TOP: Qt.CursorShape.SizeVerCursor,
    Edge.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Edge.LEFT | Edge.TOP: Qt.CursorShape.SizeFDiagCursor,
    Edge.RIGHT | Edge.BOTTOM: Qt.CursorShape.SizeFDiagCursor,
    Edge.RIGHT | Edge.TOP: Qt.CursorShape.SizeBDiagCursor,
    Edge.LEFT | Edge.BOTTOM: Qt.CursorShape.SizeBDiagCursor,
}


class FloatWindow(QWidget):
    """A frameless always-on-top window showing one screenshot."""

    closed = Signal(object)

    def __init__(self, pixmap: QPixmap, config: Config,
                 scale: float | None = None) -> None:
        super().__init__(None)
        self._pixmap = pixmap
        self._config = config
        self._scale = ui_scale() if scale is None else scale

        # Shadow padding depends only on DPI, never on window size, so it is
        # resolved once here. Everything else derives from it.
        self._shadow_cfg = config.get("shadow")
        self._pad = max(1, math.ceil(self._shadow_cfg["padding"] * self._scale))

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        # Needed for the Esc shortcut to reach keyPressEvent.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._active_edge = Edge.NONE
        self._press_pos: QPoint | None = None
        self._press_geom: tuple[int, int, int, int] | None = None

        self._metrics = self._metrics_for(pixmap.width(), pixmap.height())
        self.setGeometry(0, 0,
                         pixmap.width() + 2 * self._pad,
                         pixmap.height() + 2 * self._pad)

        self._close_opacity = 0.0
        self._close_anim = QPropertyAnimation(self, b"closeOpacity", self)
        self._close_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setWindowTitle("FloatShot")

    # -- geometry helpers ------------------------------------------------

    def _metrics_for(self, img_w: int, img_h: int) -> Metrics:
        """Element sizes for a window whose picture area is img_w x img_h."""
        cb = self._config.get("close_button")
        r = self._config.get("resize")
        return compute_metrics(
            self._scale,
            img_w + 2 * self._pad,
            img_h + 2 * self._pad,
            shadow_padding=self._shadow_cfg["padding"],
            grip_px=r["grip_px"],
            close_diameter_px=cb["diameter_px"],
            close_hit_radius_factor=cb["hit_radius_factor"],
        )

    def image_rect(self) -> QRect:
        """Where the picture sits inside the window, excluding shadow padding."""
        p = self._pad
        return QRect(p, p,
                     max(1, self.width() - 2 * p),
                     max(1, self.height() - 2 * p))

    def close_button_center(self) -> QPointF:
        """Centre of the close button: the picture's top-right corner."""
        r = self.image_rect()
        return QPointF(r.x() + r.width(), r.y())

    # -- close button opacity animation ----------------------------------

    def _get_close_opacity(self) -> float:
        return self._close_opacity

    def _set_close_opacity(self, value: float) -> None:
        self._close_opacity = value
        self.update()

    closeOpacity = Property(float, _get_close_opacity, _set_close_opacity)

    def _animate_close_button(self, target: float) -> None:
        cb = self._config.get("close_button")
        self._close_anim.stop()
        self._close_anim.setDuration(int(cb["fade_ms"]))
        self._close_anim.setStartValue(self._close_opacity)
        self._close_anim.setEndValue(target)
        self._close_anim.start()

    # -- painting --------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        try:
            self._paint_shadow(painter)
            self._paint_image(painter)
            self._paint_close_button(painter)
        finally:
            painter.end()

    def _paint_shadow(self, painter: QPainter) -> None:
        """Concentric rounded rects with falling alpha, darkest at the edge."""
        s = self._shadow_cfg
        layers = max(1, int(s["layers"]))
        max_alpha = max(0, int(s["max_alpha"]))
        offset_y = float(s["offset_y"])
        radius = float(s["radius"])
        pad = self._pad

        if max_alpha <= 0 or pad <= 0:
            return

        base = QRectF(self.image_rect())
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(layers):
            t = i / max(1, layers - 1)
            expand = pad * (1.0 - t)
            alpha = int(max_alpha * t * t)
            if alpha <= 0:
                continue
            rect = base.adjusted(-expand, -expand, expand, expand)
            rect.translate(0, offset_y * (1.0 - t))
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(rect, radius, radius)

    def _paint_image(self, painter: QPainter) -> None:
        target = self.image_rect()
        painter.drawPixmap(target, self._pixmap)

    def _paint_close_button(self, painter: QPainter) -> None:
        if self._close_opacity <= 0.01:
            return

        cb = self._config.get("close_button")
        centre = self.close_button_center()
        radius = self._metrics.close_diameter / 2.0
        alpha = max(0.0, min(1.0, self._close_opacity))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(40, 40, 40, int(200 * alpha)))
        painter.drawEllipse(centre, radius, radius)

        # A white cross, drawn as two short strokes.
        arm = radius * 0.38
        painter.setPen(QPen(QColor(255, 255, 255, int(235 * alpha)),
                            max(1.0, radius * 0.22)))
        painter.drawLine(
            QPointF(centre.x() - arm, centre.y() - arm),
            QPointF(centre.x() + arm, centre.y() + arm),
        )
        painter.drawLine(
            QPointF(centre.x() + arm, centre.y() - arm),
            QPointF(centre.x() - arm, centre.y() + arm),
        )

    # -- mouse interaction -----------------------------------------------

    def _edge_at(self, pos: QPoint) -> Edge:
        return hit_test(pos.x(), pos.y(), self.width(), self.height(),
                        self._metrics.grip)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_close_button(float(self._config.get("close_button", "hover_opacity")))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_close_button(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()

        if self._hits_close_button(event.position()):
            self.close()   # closeEvent is the single place that emits `closed`
            return

        self._press_pos = event.globalPosition().toPoint()
        self._active_edge = self._edge_at(pos)
        self._press_geom = (self.x(), self.y(), self.width(), self.height())

    def _hits_close_button(self, pos: QPointF) -> bool:
        centre = self.close_button_center()
        r = self._metrics.close_hit_radius
        return (pos.x() - centre.x()) ** 2 + (pos.y() - centre.y()) ** 2 <= r * r

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if self._press_pos is None:
            # Not dragging: just reflect what the cursor is over.
            edge = self._edge_at(pos)
            if self._hits_close_button(event.position()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(_CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
            return

        delta = event.globalPosition().toPoint() - self._press_pos
        if self._active_edge == Edge.NONE:
            self._drag_by(delta)
        else:
            self._resize_by(delta, event.modifiers())

    def _drag_by(self, delta: QPoint) -> None:
        assert self._press_geom is not None
        x, y, _, _ = self._press_geom
        self.move(x + delta.x(), y + delta.y())

    def _resize_by(self, delta: QPoint, modifiers: Qt.KeyboardModifier) -> None:
        assert self._press_geom is not None
        r = self._config.get("resize")
        lock_aspect = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        x, y, w, h = apply_resize(
            self._press_geom, self._active_edge, delta.x(), delta.y(),
            min_w=max(1, int(r["min_width"])),
            min_h=max(1, int(r["min_height"])),
        )

        if lock_aspect:
            # Constrain the picture area to the source aspect, then add the
            # shadow padding back on: padding is fixed, so the ratio applies
            # to the image region only.
            pad = self._pad
            img_w = max(1, w - 2 * pad)
            img_h = max(1, h - 2 * pad)
            src_w, src_h = self._pixmap.width(), self._pixmap.height()
            # Only one edge is dragged at a time, so a pure left/right or
            # top/bottom edge is a single flag -- corners fall through.
            if self._active_edge in (Edge.LEFT, Edge.RIGHT):
                img_w, img_h = fit_aspect_width(src_w, src_h, img_w)
            elif self._active_edge in (Edge.TOP, Edge.BOTTOM):
                img_w, img_h = fit_aspect_height(src_w, src_h, img_h)
            else:
                img_w, img_h = fit_aspect_corner(src_w, src_h, img_w, img_h)

            new_w = img_w + 2 * pad
            new_h = img_h + 2 * pad
            # Keep the edges that are not being dragged anchored.
            if Edge.LEFT in self._active_edge:
                x = self._press_geom[0] + self._press_geom[2] - new_w
            if Edge.TOP in self._active_edge:
                y = self._press_geom[1] + self._press_geom[3] - new_h
            w, h = new_w, new_h

        self.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press_pos = None
        self._press_geom = None
        self._active_edge = Edge.NONE

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._metrics = self._metrics_for(
            max(1, self.width() - 2 * self._pad),
            max(1, self.height() - 2 * self._pad),
        )
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        """The single point that announces closure, however it was triggered."""
        self._close_anim.stop()
        self.closed.emit(self)
        super().closeEvent(event)
        self.deleteLater()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()   # closeEvent is the single place that emits `closed`
            return
        super().keyPressEvent(event)
```

- [ ] **Step 2: 写一个一次性验证脚本并运行**

Run:

```bash
python -c "
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import Qt, QTimer
from pathlib import Path
import floatshot
from floatshot.config import Config
from floatshot.float_window import FloatWindow

app = QApplication([])
cfg = Config.load(Path('config.json'))

pm = QPixmap(400, 300)
pm.fill(QColor('#2E7D32'))
p = QPainter(pm)
p.setPen(QColor('white'))
p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, 'FloatShot test')
p.end()

w = FloatWindow(pm, cfg)
w.move(200, 200)
w.show()
QTimer.singleShot(15000, app.quit)
app.exec()
"
```
Expected: 出现一个绿色方块窗口，四周有柔和阴影，**没有白色边框**。用鼠标逐项确认：
1. 拖动图片中间区域 → 窗口跟随移动
2. 把鼠标移到边缘 → 光标变成对应方向的缩放箭头
3. 拖边框 → 窗口改变大小，图片跟着变形
4. 按住 `Shift` 拖边框 → 窗口按图片比例缩放，图片**不变形**
5. 鼠标移入窗口 → 右上角淡入一个小圆形按钮，带白色叉号
6. 移出窗口 → 按钮淡出
7. 点击该按钮 → 窗口关闭，脚本退出（`QApplication` 默认 `quitOnLastWindowClosed`）
8. 重跑脚本，按 `Esc` → 窗口同样关闭
9. 检查窗口**不出现在任务栏**
10. 把鼠标停在关闭按钮**视觉圆之外一点**（约半个按钮半径处）→ 光标仍是手型、点击仍能关闭，验证判定区大于视觉尺寸

- [ ] **Step 3: 提交前先按验收结果调整配置数值**

若阴影过重或过淡，编辑 `config.json` 的 `shadow.max_alpha`（默认 26）；若关闭按钮过大或过小，改 `close_button.diameter_px`（默认 16）；若边缘判定太窄或太宽，改 `resize.grip_px`（默认 6）。**改配置，不要改代码**——这是全局约束。

每改一次直接重跑 Step 2 的脚本即可看到效果，不需要重启其他东西。

- [ ] **Step 4: Commit**

```bash
git add floatshot/float_window.py
git commit -m "feat: floating window with painted shadow and hover close button"
```

---

### Task 10: 选区遮罩（overlay.py）

**Files:**
- Create: `floatshot/overlay.py`

**Interfaces:**
- Consumes: `floatshot.config.Config`、`floatshot.metrics`、`floatshot.dpi.ui_scale`
- Produces:
  - `SelectionOverlay(QWidget)` 类
    - 构造 `SelectionOverlay(origin: QRect, config: Config, scale: float | None = None)`
    - 信号 `selected = Signal(QRect)` —— 桌面坐标（非局部坐标）
    - 信号 `cancelled = Signal()`

**背景**：遮罩铺满整个虚拟桌面，暗化背景、拖拽画选区、显示尺寸提示、`Esc` 取消。因为抓屏在遮罩显示之前就完成了（Task 11 的流程），这里不需要担心把遮罩截进去。

- [ ] **Step 1: 实现 `floatshot/overlay.py`**

```python
"""Full-desktop selection overlay.

Shown after the screen has already been captured, so the darkened backdrop
and selection border can never appear in the resulting screenshot.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .config import Config
from .dpi import ui_scale

_HINT_SIZE = 12


class SelectionOverlay(QWidget):
    """Drag to select a region of the desktop.

    Emits `selected` with a rect in *desktop* coordinates (which may be
    negative on multi-monitor setups), or `cancelled` on Esc / right-click.
    """

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, origin: QRect, config: Config,
                 scale: float | None = None) -> None:
        super().__init__(None)
        self._origin = origin
        self._config = config
        self._scale = ui_scale() if scale is None else scale

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(origin)

        self._anchor: QPoint | None = None
        self._current: QPoint | None = None

    # -- selection maths --------------------------------------------------

    def _selection_local(self) -> QRect:
        if self._anchor is None or self._current is None:
            return QRect()
        return QRect(self._anchor, self._current).normalized()

    def _selection_desktop(self) -> QRect:
        return self._selection_local().translated(self._origin.topLeft())

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        try:
            self._paint_dim(painter)
            sel = self._selection_local()
            if not sel.isEmpty():
                self._paint_border(painter, sel)
                self._paint_hint(painter, sel)
        finally:
            painter.end()

    def _paint_dim(self, painter: QPainter) -> None:
        """Darken everything except the selection."""
        cfg = self._config.get("overlay")
        alpha = max(0, min(255, int(cfg["dim_alpha"])))

        path = QPainterPath()
        path.addRect(self.rect())
        sel = self._selection_local()
        if not sel.isEmpty():
            hole = QPainterPath()
            hole.addRect(sel)
            path = path.subtracted(hole)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(path, QColor(0, 0, 0, alpha))

    def _paint_border(self, painter: QPainter, sel: QRect) -> None:
        cfg = self._config.get("overlay")
        width = max(1, int(cfg["border_width"] * self._scale))
        pen = QPen(QColor(cfg["border_color"]))
        pen.setWidth(width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Inset by half the pen width so the stroke lands fully inside.
        painter.drawRect(sel.adjusted(0, 0, -1, -1))

    def _paint_hint(self, painter: QPainter, sel: QRect) -> None:
        if not self._config.get("overlay", "show_size_hint"):
            return

        text = f"{sel.width()} x {sel.height()}"
        font = QFont()
        font.setPointSize(int(_HINT_SIZE * self._scale))
        painter.setFont(font)

        metrics = painter.fontMetrics()
        pad = int(4 * self._scale)
        box = metrics.boundingRect(text).adjusted(-pad, -pad, pad, pad)

        # Prefer just above the selection; flip inside if it would go off-screen.
        y = sel.top() - box.height() - 2
        if y < 0:
            y = sel.top() + 2
        box.moveTo(sel.left(), y)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(box, 3, 3)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- input -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._anchor = event.position().toPoint()
        self._current = self._anchor
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._anchor is None:
            return
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._anchor is None:
            return
        sel = self._selection_desktop()
        self._anchor = None
        self._current = None
        if sel.width() < 2 or sel.height() < 2:
            self.cancelled.emit()
        else:
            self.selected.emit(sel)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)
```

- [ ] **Step 2: 写一个一次性验证脚本并运行**

Run:

```bash
python -c "
from PySide6.QtWidgets import QApplication
from pathlib import Path
import floatshot
from floatshot.config import Config
from floatshot.capture import virtual_geometry, grab_virtual_desktop
from floatshot.overlay import SelectionOverlay

app = QApplication([])
cfg = Config.load(Path('config.json'))
geo = virtual_geometry()

ov = SelectionOverlay(geo, cfg)
ov.selected.connect(lambda r: (print('SELECTED', r), app.quit()))
ov.cancelled.connect(lambda: (print('CANCELLED'), app.quit()))
ov.show()
app.exec()
"
```
Expected: 全屏变暗、光标变十字。逐项确认：
1. 拖拽 → 出现亮区与蓝色边框，角落跟随鼠标
2. 选区旁显示 `宽 x 高` 尺寸提示
3. 松开 → 打印 `SELECTED PySide6.QtCore.QRect(...)` 并退出
4. 重跑，按 `Esc` → 打印 `CANCELLED`
5. 重跑，单击不拖 → 打印 `CANCELLED`（小于 2×2 视为取消）
6. 重跑，右键 → 打印 `CANCELLED`

- [ ] **Step 3: Commit**

```bash
git add floatshot/overlay.py
git commit -m "feat: full-desktop selection overlay"
```

---

### Task 11: 托盘、组装与入口（tray.py + app.py + main.py）

**Files:**
- Create: `floatshot/tray.py`
- Create: `floatshot/app.py`
- Create: `main.py`

**Interfaces:**
- Consumes: 前述全部模块
- Produces:
  - `build_tray_icon(config: Config) -> QIcon`
  - `FloatShotApp(config: Config)` 类，方法 `start()`
  - `main.py` 可直接 `python main.py` 运行

**背景**：把前面所有零件接起来。关键点是**先抓后框**：热键触发后立刻抓屏，再显示遮罩。

- [ ] **Step 1: 实现 `floatshot/tray.py`**

```python
"""System tray icon and menu."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap

from .config import Config

_ICON_SIZE = 64


def build_tray_icon() -> QIcon:
    """Draw a simple camera-ish glyph so no image asset is needed."""
    pm = QPixmap(_ICON_SIZE, _ICON_SIZE)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = pm.rect().adjusted(6, 16, -6, -8)
        painter.setPen(QPen(QColor("#37474F"), 3))
        painter.setBrush(QColor("#ECEFF1"))
        painter.drawRoundedRect(body, 6, 6)

        painter.setBrush(QColor("#4A9EFF"))
        painter.setPen(Qt.PenStyle.NoPen)
        cx, cy = body.center().x(), body.center().y()
        painter.drawEllipse(cx - 9, cy - 9, 18, 18)
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
        self._icon = QSystemTrayIcon(build_tray_icon(), self)
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
```

- [ ] **Step 2: 实现 `floatshot/app.py`**

```python
"""Wires the hotkey, overlay, capture and floating windows together."""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, QRect, Qt
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
from .tray import Tray


class FloatShotApp(QObject):
    """Owns the application lifecycle."""

    def __init__(self, app: QApplication, config: Config) -> None:
        super().__init__()
        self._app = app
        self._config = config
        self._windows: list[FloatWindow] = []
        self._overlay: SelectionOverlay | None = None
        self._pending: tuple[object, QRect] | None = None

        self._tray = Tray(config, self)
        self._tray.capture_requested.connect(self.start_capture)
        self._tray.diagnostics_requested.connect(self.show_diagnostics)
        self._tray.quit_requested.connect(self.quit)

        self._hotkey = GlobalHotkey(self)
        self._hotkey.activated.connect(self.start_capture)

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._tray.show()
        if not self._register_hotkey():
            self._tray.notify(
                "FloatShot",
                f"热键注册失败：{self._hotkey.last_error}\n"
                f"可在 config.json 中修改 hotkey 后重启。",
            )
        elif self._config.get("tray", "show_startup_message"):
            self._tray.notify(
                "FloatShot",
                f"已就绪，按 {self._config.get('hotkey')} 开始截屏。",
            )

    def _register_hotkey(self) -> bool:
        spec = str(self._config.get("hotkey"))
        try:
            hotkey = parse_hotkey(spec)
        except HotkeyParseError as exc:
            self._hotkey.last_error = str(exc)
            return False
        return self._hotkey.register(hotkey)

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

        canvas, origin = grab_virtual_desktop()
        if canvas.isNull():
            self._tray.notify("FloatShot", "抓屏失败：未获取到画面。")
            return

        self._pending = (canvas, origin)
        self._overlay = SelectionOverlay(virtual_geometry(), self._config)
        self._overlay.selected.connect(self._on_selected)
        self._overlay.cancelled.connect(self._on_cancelled)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def _on_cancelled(self) -> None:
        self._pending = None
        self._dispose_overlay()

    def _dispose_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

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
        """Show the values that cannot be verified on a single-DPI machine.

        This is the check to run on a 125% / 150% display before handing the
        build to someone else: the DPI figure must match that display's
        scaling, not sit at a constant 96.
        """
        scale = ui_scale()
        dpi_value = query_system_dpi()
        shadow = self._config.get("shadow")
        resize = self._config.get("resize")
        close = self._config.get("close_button")
        pad = math.ceil(shadow["padding"] * scale)

        # Report metrics for a representative 400x300 picture.
        probe = compute_metrics(
            scale,
            400 + 2 * pad,
            300 + 2 * pad,
            shadow_padding=shadow["padding"],
            grip_px=resize["grip_px"],
            close_diameter_px=close["diameter_px"],
            close_hit_radius_factor=close["hit_radius_factor"],
        )

        geo = virtual_geometry()
        text = "\n".join([
            f"DPI 感知声明：{DPI_AWARENESS_STATUS}",
            f"系统 DPI：{dpi_value}",
            f"缩放因子：{scale:.3f}  ({scale * 100:.0f}%)",
            "",
            f"热键：{self._config.get('hotkey')}",
            "",
            f"虚拟桌面：{geo.width()} x {geo.height()}  @ ({geo.x()}, {geo.y()})",
            "",
            "以 400x300 图片为例——",
            f"  阴影内边距：{probe.padding} px",
            f"  边缘判定带：{probe.grip} px",
            f"  关闭按钮径：{probe.close_diameter} px",
            f"  按钮判定半径：{probe.close_hit_radius:.1f} px",
            "",
            f"悬浮窗数量：{len(self._windows)}",
        ])

        box = QMessageBox()
        box.setWindowTitle("FloatShot 诊断信息")
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Information)
        # Stay above the floating windows, otherwise the windows being
        # diagnosed would cover the report.
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
```

- [ ] **Step 3: 实现 `main.py`**

```python
"""FloatShot entry point.

Importing `floatshot` first is required: it disables Qt's DPI scaling and
declares DPI awareness before Qt is loaded.
"""

import sys

import floatshot  # noqa: F401  -- must be imported before PySide6

from PySide6.QtWidgets import QApplication

from floatshot.app import FloatShotApp
from floatshot.config import Config


def main() -> int:
    app = QApplication(sys.argv)
    # Closing the last floating window must not end the process -- FloatShot
    # lives in the tray.
    app.setQuitOnLastWindowClosed(False)

    config = Config.load(Config.default_path())
    if config.recovered:
        print("config.json was missing or unreadable; recreated with defaults.")

    float_shot = FloatShotApp(app, config)
    float_shot.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 给 `Config` 加 `default_path()`**

在 `floatshot/config.py` 的 `Config` 类中，`load` 之前插入：

```python
    @staticmethod
    def default_path() -> Path:
        """config.json next to the program, so it travels with the folder."""
        return Path(__file__).resolve().parent.parent / "config.json"
```

- [ ] **Step 5: 确认 config.py 的导入完整**

`config.py` 顶部应有 `from pathlib import Path`（Task 3 已包含）。Run:

```bash
python -c "from floatshot.config import Config; print(Config.default_path())"
```
Expected: 打印出 `.../floatshot/config.json` 的绝对路径。

- [ ] **Step 6: 端到端运行**

Run: `python main.py`
Expected: 无窗口出现，托盘出现图标，右下角弹出「已就绪，按 Ctrl+Alt+Q 开始截屏。」

逐项验收：
1. 打开记事本或任意窗口，按 `Ctrl+Alt+Q` → 全屏变暗、十字光标
2. 拖出一个区域 → 松手后该区域弹出悬浮窗，**位置与原选区重合**
3. 检查悬浮窗截图内容：**不应包含任何变暗的遮罩或蓝色边框**
4. 反复按热键 → 可以同时存在多个悬浮窗，各自独立
5. 逐个拖动、缩放、关闭
6. 关掉所有悬浮窗 → 程序仍在托盘运行，任务栏无残留
7. 托盘右键 → 诊断信息 → 显示 DPI、缩放因子、各元素尺寸
8. 托盘右键 → 退出 → 进程结束

- [ ] **Step 7: 验证「先抓后框」确实生效**

专门针对最容易出错的一点：按热键后**快速**点击（不拖动）。此时应打印取消、无悬浮窗。然后正常拖选一个小区域，用放大镜看悬浮窗边缘——**不应有任何暗化或蓝色像素**。若发现蓝边，说明抓屏时机错了，检查 `start_capture` 中是否先调用了 `grab_virtual_desktop()`。

- [ ] **Step 8: 验证配置真的生效**

把 `config.json` 的 `hotkey` 改成 `"Ctrl+Shift+Alt+Q"`，重启程序，确认新热键生效、旧热键失效。改回 `"Ctrl+Alt+Q"`。

这一步验证的是「不硬编码」这条全局约束。

- [ ] **Step 9: Commit**

```bash
git add floatshot/tray.py floatshot/app.py floatshot/config.py main.py
git commit -m "feat: tray, app wiring and entry point"
```

---

### Task 12: 跨 DPI 验收与打包

**Files:**
- Create: `floatshot/FloatShot.spec`（由 PyInstaller `--name FloatShot` 生成，按需修改）

**Interfaces:**
- Consumes: 完整可运行的程序
- Produces: 可分发的 exe

**背景**：spec §7.3 的验收关卡。有两件事在本机 100% 缩放下**无法验证**，必须在这里补上。

- [ ] **Step 1: 在 125% 缩放下验收**

把 Windows 缩放改为 **125%**，重新登录，然后：

Run: `python main.py`

逐项确认：
1. 托盘 → 诊断信息 → **系统 DPI 应显示 120**，缩放因子 `1.250`
2. 诊断信息中「边缘判定带」应为 **8px**（`6 × 1.25 = 7.5`，向上取整）
3. 「关闭按钮径」应为 **20px**，「阴影内边距」应为 **23px**
4. 实际截一张图，悬浮窗边缘缩放**灵敏度与 100% 时手感一致**（不应变难抓）
5. 关闭按钮**大小视觉上与 100% 时相当**，不过分小
6. 截图内容**清晰不模糊**（若模糊，说明 DPI 感知没生效）

若第 6 项失败，回到 `floatshot/__init__.py` 检查 `declare_dpi_awareness()` 是否真的在 Qt import 前执行。

- [ ] **Step 2: 在 150% 下重复 Step 1**

系统 DPI 应为 **144**，缩放因子 `1.500`，判定带 `9px`，按钮径 `24px`，内边距 `27px`。

- [ ] **Step 3: 切回 100% 并确认无回归**

改回 100%，重启，确认诊断信息显示 DPI 96、缩放 1.000、判定带 6px、按钮径 16px。

- [ ] **Step 4: 打包**

```bash
pip install pyinstaller
python -m PyInstaller --onefile --noconsole --name FloatShot main.py
```

- [ ] **Step 5: 打包产物验收（关键）**

这一步验证的是 spec §2.3 中记录的未验证项——**exe 使用 PyInstaller 自己的 bootloader manifest，可能不声明 DPI 感知**。

在一个**没有安装 Python 的环境**或**全新的 Windows 用户账号**下运行 `dist/FloatShot.exe`：

1. 程序能启动，托盘出现图标
2. 若无 Python 的机器不方便准备，至少用一个全新的 Windows 用户账号测试
3. **在 125% 或 150% 缩放下运行 exe**，打开诊断信息，**系统 DPI 必须正确显示 120 或 144**
4. 若显示恒定的 96：说明 exe 未声明 DPI 感知。解决办法是在 PyInstaller 的 spec 里通过 `EXE(..., manifest=...)` 指定一个声明 `dpiAware`/`dpiAwareness` 的 manifest 文件。用例：

```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">permonitorv2</dpiAwareness>
    </windowsSettings>
  </application>
</assembly>
```

5. 全局热键在新环境下能注册成功
6. 抓屏正常，无黑屏

**必须通过第 3 项才能对外分发。** 这一项在全流程中只在此处可验证。

- [ ] **Step 6: 确认 config.json 与 exe 的相对位置正确**

把 `dist/FloatShot.exe` 单独复制到一个空目录，双击运行。确认：
1. 同目录下自动生成了 `config.json`
2. 修改该文件的 `hotkey` 后重启 exe，新热键生效

这验证了 `Config.default_path()` 在打包环境下解析正确。若失败，检查 `Path(__file__).resolve().parent.parent` 在 PyInstaller 的 `_MEIPASS` 临时目录下的行为，必要时改用 `sys.executable` 的目录。

- [ ] **Step 7: Commit**

```bash
git add FloatShot.spec
git commit -m "chore: pyinstaller build config"
```

---

## 完成标准

全部任务完成后应满足：

- `python -m pytest -v` 全绿
- `python main.py` 端到端可用，spec §7.2 的手动验收项全部通过
- 125% / 150% 缩放下诊断信息的 DPI 数值正确（spec §7.3 第 1 项）
- 打包后的 exe 在无 Python 环境下 DPI 探测正确（spec §7.3，唯一无法在开发机验证的关卡）
- 改 `config.json` 能改变热键、阴影、按钮尺寸，无需改代码

## 已知未决项

- **多显示器 DPI 不一致**：程序用系统 DPI 而非 per-monitor，跨屏拖动时元素尺寸不随屏幕更新。spec §8 已记录为已知限制，首版接受。
- **阴影观感**：`shadow.max_alpha` 等数值是初值，需按 Task 9 Step 3 边看边调。
