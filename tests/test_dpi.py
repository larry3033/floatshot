import os
import subprocess
import sys
import textwrap
from pathlib import Path

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


# ---------- 包初始化：import 期副作用 ----------
#
# These run in a fresh interpreter. The pytest process already imported
# floatshot via the test modules above, so an in-process assertion would
# observe the env vars as already-set and would prove nothing at all about
# import-time ordering -- which is the only thing worth testing here.

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_PROBE = textwrap.dedent(
    """
    import os
    import sys

    import floatshot

    # The env vars below only have an effect if they are set before Qt is
    # imported, so prove Qt is still absent once floatshot has finished
    # importing. This is the assertion that actually guards the ordering.
    assert "PySide6" not in sys.modules, "PySide6 was already imported"

    print("QT_ENABLE_HIGHDPI_SCALING=" + os.environ["QT_ENABLE_HIGHDPI_SCALING"])
    print("QT_SCALE_FACTOR=" + os.environ["QT_SCALE_FACTOR"])
    status = floatshot.DPI_AWARENESS_STATUS
    print("STATUS_IS_NONEMPTY_STR=" + str(isinstance(status, str) and bool(status)))
    """
)


def _run_probe(env=None):
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=_PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _probe_report(proc, expectation):
    return (
        f"import-time probe expected {expectation}, "
        f"got return code {proc.returncode}\n"
        f"--- probe stdout ---\n{proc.stdout}"
        f"--- probe stderr ---\n{proc.stderr}"
    )


def _assert_probe_value(proc, key, want, why):
    values = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    got = values.get(key)
    assert got == want, (
        f"{key}: expected {want!r}, got {got!r}\n"
        f"  why this matters: {why}\n"
        f"{_probe_report(proc, f'{key}={want}')}"
    )


def test_package_init_sets_dpi_env_vars_before_qt_loads():
    proc = _run_probe()
    assert proc.returncode == 0, _probe_report(proc, "return code 0")

    _assert_probe_value(
        proc, "QT_ENABLE_HIGHDPI_SCALING", "0",
        "Qt's scaling must stay off, or logical coordinates stop matching "
        "physical pixels and captures land on the wrong region on a scaled "
        "display -- a failure invisible at 100%",
    )
    _assert_probe_value(
        proc, "QT_SCALE_FACTOR", "1",
        "a scale factor other than 1 reintroduces the logical/physical "
        "mismatch that disabling Qt's scaling exists to remove",
    )
    _assert_probe_value(
        proc, "STATUS_IS_NONEMPTY_STR", "True",
        "floatshot/__init__.py must store dpi.declare_dpi_awareness() in "
        "DPI_AWARENESS_STATUS as a non-empty str; the tray diagnostics panel "
        "reports it",
    )


def test_package_init_overrides_an_inherited_environment():
    # The env vars are set by direct assignment, not setdefault, so that a
    # polluted parent environment cannot silently win. Feeding the probe a
    # deliberately wrong inherited environment is the only way to observe
    # the difference between the two.
    proc = _run_probe(
        env={
            **os.environ,
            "QT_ENABLE_HIGHDPI_SCALING": "1",
            "QT_SCALE_FACTOR": "2",
        }
    )
    assert proc.returncode == 0, _probe_report(proc, "return code 0")

    _assert_probe_value(
        proc, "QT_ENABLE_HIGHDPI_SCALING", "0",
        "an inherited QT_ENABLE_HIGHDPI_SCALING=1 was allowed to win, so the "
        "assignment is not unconditional (setdefault regression)",
    )
    _assert_probe_value(
        proc, "QT_SCALE_FACTOR", "1",
        "an inherited QT_SCALE_FACTOR=2 was allowed to win, so the assignment "
        "is not unconditional (setdefault regression)",
    )
