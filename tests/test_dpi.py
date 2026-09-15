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
