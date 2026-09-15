"""FloatShot -- screenshot to floating window.

The environment variables and the DPI-awareness call below MUST run before
Qt is imported. Qt reads these settings once, at first import, and silently
ignores later changes -- a mistake here would not crash, it would just make
captures land on the wrong pixels on a scaled display, which is invisible
on a 100% display.

Living in __init__.py rather than main.py is deliberate: every import path
into this package runs this file first, so no entry point can bypass it.

Disabling Qt's scaling means logical coordinates equal physical pixels, so
capture and mouse coordinates line up with no conversion. The cost is that
Qt widgets no longer grow on high-DPI displays; UI element sizes are scaled
manually instead, via floatshot.dpi.ui_scale().
"""

import os

os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

from . import dpi  # noqa: E402  -- must follow the env vars above

# Kept rather than discarded: the tray's diagnostics panel reports this,
# which is how a packaged build gets checked for DPI awareness.
DPI_AWARENESS_STATUS = dpi.declare_dpi_awareness()
