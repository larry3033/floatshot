"""Data model for the Qt settings window.

Pure Python -- no Qt import -- so the menu structure can be unit tested and
inspected, while settings_window.py turns it into widgets. Keeping the set of
exposed options in one list is what stops the form and the config from
drifting apart.

`keys` is the path into the config; `kind` selects the widget.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    """One editable setting.

    `kind` is one of: section, bool, int, float, color, choice, text,
    lines, action.
    section items are group headers and carry only a label; a `lines` item
    is edited as one entry per line (used for the AI preset prompts).
    """

    label: str
    keys: tuple[str, ...] = ()
    kind: str = "action"
    step: float = 1.0
    minimum: float | None = None
    maximum: float | None = None
    action: str = ""
    choices: tuple[str, ...] = ()   # for kind="choice"
    secret: bool = False            # for kind="text": mask the field


MENU: tuple[Item, ...] = (
    Item("截图快捷键", ("hotkey",), kind="text"),
    Item("截图后复制到剪贴板", ("capture", "copy_to_clipboard"), kind="bool"),

    Item("悬浮窗", kind="section"),
    Item("阴影内边距", ("shadow", "padding"), kind="int", minimum=0),
    Item("阴影层数", ("shadow", "layers"), kind="int", minimum=1),
    Item("阴影透明度", ("shadow", "max_alpha"),
         kind="int", minimum=0, maximum=255),
    Item("描边显示", ("outline", "enabled"), kind="bool"),
    Item("描边颜色", ("outline", "color"), kind="color"),
    Item("描边宽度", ("outline", "width_px"), kind="int", minimum=1),
    Item("角点显示", ("corner_dots", "enabled"), kind="bool"),
    Item("角点颜色", ("corner_dots", "color"), kind="color"),
    Item("角点直径", ("corner_dots", "diameter_px"), kind="int", minimum=2),

    Item("标注", kind="section"),
    Item("描边颜色", ("annotation", "stroke_color"), kind="color"),
    Item("描边宽度", ("annotation", "stroke_width"), kind="int", minimum=1),
    Item("高亮颜色", ("annotation", "highlight_color"), kind="color"),
    Item("高亮宽度", ("annotation", "highlight_width"), kind="int", minimum=1),
    Item("高亮透明度", ("annotation", "highlight_alpha"),
         kind="int", step=5, minimum=0, maximum=255),
    Item("马赛克块大小", ("annotation", "mosaic_block"),
         kind="int", minimum=2),
    Item("马赛克笔刷", ("annotation", "mosaic_brush"), kind="int", minimum=2),
    Item("文字字号", ("annotation", "text_font_px"), kind="int", minimum=6),

    Item("AI 识别", kind="section"),
    Item("接口格式", ("ai", "format"), kind="choice",
         choices=("openai", "claude")),
    Item("接口地址", ("ai", "base_url"), kind="text"),
    Item("模型", ("ai", "model"), kind="text"),
    Item("API Key", ("ai", "api_key"), kind="text", secret=True),
    Item("Key 环境变量", ("ai", "api_key_env"), kind="text"),
    Item("超时（秒）", ("ai", "timeout_s"),
         kind="float", minimum=1, maximum=600),
    Item("最大回复长度", ("ai", "max_tokens"),
         kind="int", minimum=1, maximum=120000),
    Item("系统提示词", ("ai", "system_prompt"), kind="text"),
    Item("预制提示词", ("ai", "presets"), kind="lines"),

    Item("操作", kind="section"),
    Item("立即截屏", kind="action", action="capture"),
    Item("诊断信息", kind="action", action="diagnostics"),
    Item("退出程序", kind="action", action="quit"),
)

# Items that carry no config value and are never written back.
NON_CONFIG_KINDS = frozenset({"section", "action"})


def grouped(menu: tuple[Item, ...] = MENU) -> list[tuple[str, list[Item]]]:
    """Split the flat menu into (group title, items) pairs.

    Items before the first section form a leading group, so a menu need not
    open with a header.
    """
    groups: list[tuple[str, list[Item]]] = []
    title = "常规"
    current: list[Item] | None = None
    for item in menu:
        if item.kind == "section":
            title = item.label
            current = None
            continue
        if current is None:
            current = []
            groups.append((title, current))
        current.append(item)
    return groups


def list_to_lines(values: object) -> str:
    """Render a list setting (the AI presets) as one item per line."""
    if not isinstance(values, (list, tuple)):
        return ""
    return "\n".join(str(value) for value in values)


def lines_to_list(text: str) -> list[str]:
    """Parse the preset editor back into a list, dropping blank lines."""
    return [line.strip() for line in str(text or "").splitlines()
            if line.strip()]
