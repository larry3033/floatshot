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
