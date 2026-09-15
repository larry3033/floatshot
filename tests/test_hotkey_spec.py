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
