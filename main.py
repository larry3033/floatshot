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
    # A windowed (--noconsole) build has no stdout to print to.
    if config.recovered and sys.stdout is not None:
        print("config.json 缺失或损坏，已用默认值重建。", flush=True)

    float_shot = FloatShotApp(app, config)
    float_shot.start()   # shows the tray and drops into the console menu
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
