"""Hand-built recordings the renderer tests and the goldens share.

These are written out rather than captured, so a golden file describes what
the renderer does and nothing else. A change in the screen model cannot churn
them, and a change in the renderer shows up as a readable diff.

This module does not match the discovery pattern, so it is never collected as
a test.
"""

from __future__ import annotations

import dataclasses
from typing import Final

from ptyreel.recording import NEVER, LineVersion, Recording, Style
from ptyreel.tape import TapeSettings

COLS: Final[int] = 20
BASE: Final[TapeSettings] = TapeSettings(
    width=400, height=300, title="fixture", loop_delay_ms=1_000
)


def line(
    index: int,
    text: str,
    *,
    start_ms: int,
    step_ms: int = 0,
    styles: tuple[int, ...] | None = None,
    birth_ms: int = 0,
    death_ms: int = NEVER,
    cols: int = COLS,
) -> LineVersion:
    """Build one line version from a string and a typing rhythm.

    Parameters
    ----------
    index : int
        Absolute line index.
    text : str
        Visible characters. The rest of the line stays blank.
    start_ms : int
        When the first character appears.
    step_ms : int, optional
        Gap between characters. Zero reveals the whole line at once.
    styles : tuple of int or None, optional
        Style index per character. Defaults to the plain style.
    birth_ms, death_ms : int, optional
        Lifetime of this version.
    cols : int, optional
        Width of the line.

    Returns
    -------
    LineVersion
        A version padded to ``cols``.
    """
    padded = text.ljust(cols)[:cols]
    times = tuple(
        start_ms + step_ms * position if position < len(text) else NEVER
        for position in range(cols)
    )
    table = styles or (0,) * len(text)
    cells = tuple(
        table[position] if position < len(table) else 0 for position in range(cols)
    )
    return LineVersion(
        line=index,
        birth_ms=birth_ms,
        death_ms=death_ms,
        chars=padded,
        styles=cells,
        times=times,
    )


_STYLED_TABLE: Final[tuple[Style, ...]] = (
    Style(),
    Style(fg=1),
    Style(fg=2),
    Style(fg=4),
    Style(fg=9),
    Style(fg=14),
    Style(bold=True),
    Style(italic=True),
    Style(underline=True),
    Style(dim=True),
    Style(fg=3, bold=True, underline=True),
)

_MINIMAL: Final[Recording] = Recording(
    cols=COLS,
    rows=3,
    duration_ms=1_000,
    styles=(Style(),),
    lines=(line(0, "$ hi", start_ms=0, step_ms=200),),
    scrolls=((0, 0),),
    cursors=((0, 0, 0), (600, 0, 4)),
)

_STYLED: Final[Recording] = Recording(
    cols=COLS,
    rows=4,
    duration_ms=800,
    styles=_STYLED_TABLE,
    lines=(
        line(
            0,
            "0123456789",
            start_ms=0,
            styles=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
        ),
        line(1, "mixed", start_ms=400, styles=(10,) * 5),
    ),
    scrolls=((0, 0),),
    cursors=((0, 0, 0), (400, 1, 5)),
)

_ESCAPING: Final[Recording] = Recording(
    cols=COLS,
    rows=3,
    duration_ms=600,
    styles=(Style(),),
    lines=(
        line(0, "a < b & c > d", start_ms=0),
        line(1, '"q" \'p\' ]]>', start_ms=300),
        line(2, "é 中   ok", start_ms=600),
    ),
    scrolls=((0, 0),),
    cursors=((0, 0, 0),),
)

_BUCKETS: Final[Recording] = Recording(
    cols=COLS,
    rows=3,
    duration_ms=4_000,
    styles=(Style(), Style(fg=2)),
    lines=(
        line(0, "aa", start_ms=0, step_ms=10),
        line(1, "50%", start_ms=100, birth_ms=100, death_ms=900),
        line(1, "100%", start_ms=900, birth_ms=900),
        line(2, "done", start_ms=3_900, styles=(1, 1, 1, 1)),
    ),
    scrolls=((0, 0), (3_900, 1)),
    cursors=((0, 0, 0), (900, 1, 4), (3_900, 2, 4)),
)

RECORDINGS: Final[dict[str, Recording]] = {
    "minimal": _MINIMAL,
    "styled": _STYLED,
    "once": _MINIMAL,
    "escaping": _ESCAPING,
    "buckets": _BUCKETS,
}

SETTINGS: Final[dict[str, TapeSettings]] = {
    "minimal": BASE,
    "styled": BASE,
    "once": dataclasses.replace(BASE, loop=False),
    "escaping": dataclasses.replace(
        BASE, title='a <script>alert(1)</script> "x" & \'y\''
    ),
    "buckets": dataclasses.replace(BASE, theme="github-light"),
}
