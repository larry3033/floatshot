"""The Qt configuration window -- FloatShot's main interface.

Built from the pure Item list in settings.py so adding a setting is a
one-line change there. Every edit is written straight back to config.json;
the screenshot hotkey is validated and re-registered live.

Qt scaling is disabled process-wide (see floatshot/__init__.py), so the base
font is scaled by the system DPI here to keep the window readable on a
high-DPI display.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import Config
from .dpi import ui_scale
from .hotkey_spec import HotkeyParseError, parse_hotkey
from .settings import Item, grouped, lines_to_list, list_to_lines


class _LinesEdit(QPlainTextEdit):
    """A multi-line editor that reports when it loses focus.

    QPlainTextEdit has no editingFinished, which is what the form needs to
    avoid saving on every keystroke.
    """

    committed = Signal()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.committed.emit()


class SettingsWindow(QWidget):
    """Form of every configurable value, plus a few actions."""

    capture_requested = Signal()
    diagnostics_requested = Signal()
    quit_requested = Signal()
    hotkey_changed = Signal(str)

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._scale = ui_scale()
        self._hotkey_edit: QLineEdit | None = None
        self._hotkey_status: QLabel | None = None

        self.setWindowTitle("FloatShot 配置")
        # Float above the always-on-top screenshot windows, or it would be
        # impossible to reach once a few are pasted.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        font = QFont()
        font.setPixelSize(max(11, int(14 * self._scale)))
        self.setFont(font)

        self._build()
        # A fixed initial size keeps the window from jumping as tabs change
        # to pages of different heights.
        self.setMinimumSize(440, 420)
        self.resize(460, 520)

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # One tab per config group: a single flat form had grown far too long
        # to scan.
        tabs = QTabWidget()
        for group_title, items in grouped():
            page = QWidget()
            form = QFormLayout(page)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for item in items:
                self._add_item(form, item)
            tabs.addTab(page, group_title)
        root.addWidget(tabs)

        hint = QLabel("修改即时生效并写入 config.json。关闭此窗口不会退出程序，"
                      "可从托盘“打开主界面”再打开。")
        hint.setWordWrap(True)
        root.addWidget(hint)

    def _add_item(self, form: QFormLayout, item: Item) -> None:
        if item.kind == "bool":
            editor = QCheckBox()
            editor.setChecked(bool(self._config.get(*item.keys)))
            editor.toggled.connect(lambda value, it=item: self._write(it, value))
            form.addRow(item.label, editor)
        elif item.kind == "int":
            editor = QSpinBox()
            editor.setRange(int(item.minimum if item.minimum is not None else 0),
                            int(item.maximum if item.maximum is not None else 9999))
            editor.setSingleStep(max(1, int(item.step)))
            editor.setValue(int(self._config.get(*item.keys)))
            editor.valueChanged.connect(
                lambda value, it=item: self._write(it, value))
            form.addRow(item.label, editor)
        elif item.kind == "float":
            editor = QDoubleSpinBox()
            editor.setDecimals(3)
            editor.setSingleStep(item.step)
            if item.minimum is not None:
                editor.setMinimum(item.minimum)
            if item.maximum is not None:
                editor.setMaximum(item.maximum)
            editor.setValue(float(self._config.get(*item.keys)))
            editor.valueChanged.connect(
                lambda value, it=item: self._write(it, value))
            form.addRow(item.label, editor)
        elif item.kind == "color":
            editor = QPushButton()
            self._paint_swatch(editor, str(self._config.get(*item.keys)))
            editor.clicked.connect(
                lambda _=False, it=item, b=editor: self._pick_color(it, b))
            form.addRow(item.label, editor)
        elif item.kind == "choice":
            editor = QComboBox()
            editor.addItems(item.choices)
            current = str(self._config.get(*item.keys))
            if current in item.choices:
                editor.setCurrentText(current)
            editor.currentTextChanged.connect(
                lambda value, it=item: self._write(it, value))
            form.addRow(item.label, editor)
        elif item.kind == "text":
            # The hotkey gets the validate-and-register editor; everything
            # else is a plain line edit.
            if item.keys == ("hotkey",):
                self._add_hotkey(form, item)
            else:
                editor = QLineEdit(str(self._config.get(*item.keys)))
                if item.secret:
                    editor.setEchoMode(QLineEdit.EchoMode.Password)
                editor.editingFinished.connect(
                    lambda it=item, e=editor: self._write(it, e.text()))
                form.addRow(item.label, editor)
        elif item.kind == "lines":
            editor = _LinesEdit()
            editor.setPlainText(list_to_lines(self._config.get(*item.keys)))
            editor.setFixedHeight(90)
            editor.committed.connect(
                lambda it=item, e=editor:
                self._write(it, lines_to_list(e.toPlainText())))
            form.addRow(item.label, editor)
        elif item.kind == "action":
            editor = QPushButton(item.label)
            editor.clicked.connect(
                lambda _=False, it=item: self._run_action(it.action))
            form.addRow(editor)

    def _add_hotkey(self, form: QFormLayout, item: Item) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(self._config.get(*item.keys)))
        edit.setPlaceholderText("如 Ctrl+Alt+Q")
        apply_button = QPushButton("应用")
        layout.addWidget(edit)
        layout.addWidget(apply_button)
        form.addRow(item.label, row)

        status = QLabel("")
        form.addRow("", status)
        self._hotkey_edit = edit
        self._hotkey_status = status

        apply_button.clicked.connect(self._apply_hotkey)
        edit.returnPressed.connect(self._apply_hotkey)

    # -- editing ----------------------------------------------------------

    def _write(self, item: Item, value) -> None:
        self._config.set(*item.keys, value=value)
        self._save()

    def _save(self) -> None:
        try:
            self._config.save()
        except Exception as exc:
            self._show_hotkey_status(False, f"保存失败：{exc}")

    def _pick_color(self, item: Item, button: QPushButton) -> None:
        current = QColor(str(self._config.get(*item.keys)))
        chosen = QColorDialog.getColor(current, self, item.label)
        if not chosen.isValid():
            return
        self._config.set(*item.keys, value=chosen.name())
        self._paint_swatch(button, chosen.name())
        self._save()

    def _apply_hotkey(self) -> None:
        assert self._hotkey_edit is not None
        spec = self._hotkey_edit.text().strip()
        try:
            hotkey = parse_hotkey(spec)
        except HotkeyParseError as exc:
            self._show_hotkey_status(False, f"无效：{exc}")
            return
        self._hotkey_edit.setText(hotkey.text)
        self._config.set("hotkey", value=hotkey.text)
        self._save()
        # The app slot registers it and calls back with the outcome.
        self.hotkey_changed.emit(hotkey.text)

    def show_hotkey_status(self, ok: bool, message: str) -> None:
        self._show_hotkey_status(ok, message)

    def _show_hotkey_status(self, ok: bool, message: str) -> None:
        if self._hotkey_status is None:
            return
        self._hotkey_status.setStyleSheet(
            "color: #2FBF71;" if ok else "color: #E5484D;")
        self._hotkey_status.setText(message)

    def _run_action(self, action: str) -> None:
        if action == "capture":
            self.capture_requested.emit()
        elif action == "diagnostics":
            self.diagnostics_requested.emit()
        elif action == "quit":
            self.quit_requested.emit()

    @staticmethod
    def _paint_swatch(button: QPushButton, colour: str) -> None:
        swatch = QColor(colour)
        # Pick readable text against the swatch itself.
        luminance = (0.299 * swatch.red() + 0.587 * swatch.green()
                     + 0.114 * swatch.blue())
        foreground = "#000000" if luminance > 150 else "#FFFFFF"
        button.setText(colour)
        button.setStyleSheet(
            f"background-color: {colour}; color: {foreground};"
        )

    # -- window behaviour -------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        # Closing the main interface only hides it: FloatShot lives in the
        # tray, and quitting is an explicit menu entry.
        event.ignore()
        self.hide()
