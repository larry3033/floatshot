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
