"""Single-line AI query bar shown under a floating window.

Collapsed it is one row -- preset picker, free-form input, send, close.
Sending expands a small result panel underneath. The request runs on a
worker thread and the answer returns through queued signals, so the bar
never blocks.

Prompt rule: whatever is in the input box is the question; if the box is
empty the configured system prompt is sent as the question instead.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .ai_client import ask, resolve_key
from .config import Config
from .dpi import ui_scale


class AiBar(QWidget):
    """Ask the vision model about this picture, inline under the window."""

    _result = Signal(str)
    _error = Signal(str)
    resized = Signal()   # the result panel grew/shrank; reposition me

    def __init__(self, config: Config, image: QPixmap) -> None:
        super().__init__(None)
        self._config = config
        self._ai = config.get("ai")
        self._cfg = config.get("toolbar")
        self._busy = False

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        font = QFont()
        font.setPixelSize(max(11, int(14 * ui_scale())))
        self.setFont(font)

        self._build()
        self._result.connect(self._on_result)
        self._error.connect(self._on_error)
        self.set_image(image)

    # -- construction -----------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        pad = max(4, int(int(self._cfg["padding"]) * 0.7))
        root.setContentsMargins(pad, pad, pad, pad)
        root.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(int(self._cfg["spacing"]))

        row.addWidget(QLabel("AI"))

        self._presets = QComboBox()
        self._presets.addItems([str(p) for p in (self._ai.get("presets") or [])])
        self._presets.activated.connect(self._on_preset)
        row.addWidget(self._presets)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入问题，回车发送；留空则发送系统提示词")
        self._input.returnPressed.connect(lambda: self._send(None))
        row.addWidget(self._input, 1)

        send = QPushButton("发送")
        send.clicked.connect(lambda: self._send(None))
        row.addWidget(send)

        close = QPushButton("×")
        close.setFixedWidth(28)
        close.clicked.connect(self.hide)
        row.addWidget(close)

        root.addLayout(row)

        self._result_view = QPlainTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setMinimumHeight(120)
        self._result_view.hide()
        root.addWidget(self._result_view)

    # -- image ------------------------------------------------------------

    def set_image(self, image: QPixmap) -> None:
        self._image = image

    def _png_bytes(self) -> bytes:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        self._image.save(buffer, "PNG")
        buffer.close()
        return bytes(data)

    # -- sending ----------------------------------------------------------

    def _on_preset(self, _index: int) -> None:
        self._send(self._presets.currentText())

    def _send(self, prompt: str | None) -> None:
        if self._busy:
            return
        text = (prompt if prompt is not None else self._input.text()).strip()
        if not text:
            # Empty box: fall back to the configured system prompt.
            text = str(self._ai.get("system_prompt", "")).strip()
        if not text:
            self._expand()
            self._result_view.setPlainText("没有可发送的提示词。")
            return
        if not str(self._ai.get("base_url", "")).strip():
            self._expand()
            self._result_view.setPlainText("未配置接口地址（config.json 的 ai.base_url）。")
            return
        if not resolve_key(self._ai):
            self._expand()
            self._result_view.setPlainText("未配置 API Key（config.json 的 ai.api_key）。")
            return

        self._busy = True
        self._expand()
        self._result_view.setPlainText(f"请求中…（{self._ai.get('model')}）")
        threading.Thread(
            target=self._request, args=(text,), daemon=True
        ).start()

    def _request(self, prompt: str) -> None:
        try:
            answer = ask(self._ai, prompt, self._png_bytes())
        except Exception as exc:
            self._error.emit(str(exc))
        else:
            self._result.emit(answer)

    def _on_result(self, text: str) -> None:
        self._busy = False
        self._result_view.setPlainText(text)

    def _on_error(self, message: str) -> None:
        self._busy = False
        self._result_view.setPlainText(f"请求失败：\n{message}")

    def _expand(self) -> None:
        if not self._result_view.isVisible():
            self._result_view.show()
            self.adjustSize()
            self.resized.emit()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            radius = float(self._cfg["radius"])
            painter.setBrush(QColor(self._cfg["background"]))
            painter.setPen(QPen(QColor(self._cfg["border_color"]), 1))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
            )
        finally:
            painter.end()
