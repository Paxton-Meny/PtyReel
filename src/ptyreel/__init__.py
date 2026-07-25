"""Record scripted terminal sessions as self-contained animated SVGs.

The supported interface is the command line and the action inputs. Importing
this package works and the names below are the ones worth reaching for, but
nothing is frozen before version 1.0.

Only the pure parts are re-exported here, so importing PtyReel never pulls in
a module that needs POSIX. The two entry points that run a session are reached
by their own paths: ``from ptyreel.pipeline import render_tape`` and
``from ptyreel.driver import run_tape``. Both need ``pty``, ``termios`` and
``fcntl``.
"""

from __future__ import annotations

from ptyreel.errors import (
    DriverError,
    PathSecurityError,
    PtyReelError,
    RenderError,
    TapeError,
)
from ptyreel.parse import load_tape, parse_tape
from ptyreel.recording import NEVER, LineVersion, Recording, Style
from ptyreel.svg import render_svg
from ptyreel.tape import Tape, TapeSettings
from ptyreel.theme import THEMES, Theme

__version__ = "0.1.0"

__all__ = [
    "NEVER",
    "THEMES",
    "DriverError",
    "LineVersion",
    "PathSecurityError",
    "PtyReelError",
    "Recording",
    "RenderError",
    "Style",
    "Tape",
    "TapeError",
    "TapeSettings",
    "Theme",
    "__version__",
    "load_tape",
    "parse_tape",
    "render_svg",
]
