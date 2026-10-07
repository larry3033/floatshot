from floatshot.settings import (
    MENU,
    NON_CONFIG_KINDS,
    Item,
    grouped,
    lines_to_list,
    list_to_lines,
)


def test_menu_opens_with_a_leading_group():
    groups = grouped(MENU)
    assert groups[0][0] == "常规"
    # The hotkey is the first thing a user looks for.
    assert groups[0][1][0].keys == ("hotkey",)


def test_group_titles_follow_the_sections():
    titles = [title for title, _ in grouped(MENU)]
    assert titles == ["常规", "悬浮窗", "标注", "AI 识别", "操作"]


def test_every_config_item_has_a_key_path():
    for item in MENU:
        if item.kind not in NON_CONFIG_KINDS:
            assert item.keys, item


def test_section_and_action_items_carry_no_config_keys():
    for item in MENU:
        if item.kind in NON_CONFIG_KINDS:
            assert not item.keys, item


def test_capture_action_is_present():
    actions = {item.action for item in MENU if item.kind == "action"}
    assert {"capture", "diagnostics", "quit"} <= actions


def test_numeric_bounds_are_sane():
    for item in MENU:
        if item.kind in ("int", "float"):
            if item.minimum is not None and item.maximum is not None:
                assert item.minimum <= item.maximum, item


def test_grouped_does_not_mutate_the_menu():
    before = tuple(MENU)
    grouped(MENU)
    assert tuple(MENU) == before


def test_item_defaults_are_an_action():
    assert Item("x").kind == "action"


# ---------- list <-> lines ----------

def test_presets_item_is_a_lines_editor():
    item = next(i for i in MENU if i.keys == ("ai", "presets"))
    assert item.kind == "lines"


def test_list_to_lines_round_trips():
    values = ["one", "two", "three"]
    assert lines_to_list(list_to_lines(values)) == values


def test_lines_to_list_drops_blanks_and_trims():
    assert lines_to_list("  a \n\n b\n   \n") == ["a", "b"]


def test_list_to_lines_tolerates_junk():
    assert list_to_lines(None) == ""
    assert list_to_lines("not a list") == ""
