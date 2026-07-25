"""Every pixel and grid measurement, derived once from a tape's settings.

The driver needs the grid size to tell the pseudo-terminal how wide the screen
is. The renderer needs the same numbers plus every coordinate in the window.
Computing them in two places would let the two drift apart, so they are
computed once here and passed around. No other module does arithmetic on
``width``, ``height``, ``padding`` or ``font_size``.

Font metrics live here rather than in a theme, because changing a palette must
not change where a character sits. The character advance assumes a monospace
face at 0.6 em, which every font in the stack matches. The renderer does not
depend on that being exact: each run of text is drawn with an explicit start
position and an explicit total width, so a reader whose machine falls back to
a different monospace font still sees columns line up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ptyreel.tape import TapeSettings

__all__ = [
    "CHAR_WIDTH_RATIO",
    "FONT_STACK",
    "LINE_HEIGHT_RATIO",
    "MAX_COLS",
    "MAX_LINES",
    "MAX_ROWS",
    "MIN_COLS",
    "MIN_ROWS",
    "Layout",
]

CHAR_WIDTH_RATIO: Final[float] = 0.6
LINE_HEIGHT_RATIO: Final[float] = 1.6
FONT_STACK: Final[str] = (
    "'Fira Code', 'JetBrains Mono', 'SF Mono', 'Cascadia Code', "
    "'DejaVu Sans Mono', Consolas, monospace"
)

MIN_COLS: Final[int] = 20
MAX_COLS: Final[int] = 500
MIN_ROWS: Final[int] = 4
MAX_ROWS: Final[int] = 200
MAX_LINES: Final[int] = 2_000


@dataclass(frozen=True, slots=True, kw_only=True)
class Layout:
    """Resolved geometry for one rendered window.

    Attributes
    ----------
    width, height : int
        Size of the whole image.
    font_size : int
        Text size in pixels.
    char_width : int
        Horizontal advance of one cell.
    line_height : int
        Vertical distance between baselines.
    cols, rows : int
        Size of the terminal grid.
    window_x, window_y, window_width, window_height : int
        The terminal window inside the image.
    window_radius : int
        Corner radius of the window.
    backdrop_radius : int
        Corner radius of the image background.
    title_bar_height : int
        Height of the strip holding the window controls.
    light_radius, light_x, light_y, light_gap : int
        Geometry of the three window controls.
    content_x, content_top : int
        Top left corner of the text area.
    baseline_offset : int
        Distance from the top of a line box down to its baseline.
    cursor_width, cursor_height, cursor_offset : int
        Size of the cursor block and how far above the baseline it starts.
    """

    width: int
    height: int
    font_size: int
    char_width: int
    line_height: int
    cols: int
    rows: int
    window_x: int
    window_y: int
    window_width: int
    window_height: int
    window_radius: int
    backdrop_radius: int
    title_bar_height: int
    light_radius: int
    light_x: int
    light_y: int
    light_gap: int
    content_x: int
    content_top: int
    baseline_offset: int
    cursor_width: int
    cursor_height: int
    cursor_offset: int

    @classmethod
    def from_settings(cls, settings: TapeSettings) -> Layout:
        """Derive a layout from a tape's settings.

        Parameters
        ----------
        settings : TapeSettings
            Validated settings. The parser has already bounded every input,
            so only the derived grid size can still fall out of range.

        Returns
        -------
        Layout
            Geometry with a grid size clamped into the supported range.

        Raises
        ------
        ValueError
            If the requested image is too small to hold a usable grid, which
            happens when a large font is asked to fit a small window.
        """
        font_size = settings.font_size
        char_width = max(1, round(font_size * CHAR_WIDTH_RATIO))
        line_height = max(2, round(font_size * LINE_HEIGHT_RATIO))

        margin_x = max(8, round(settings.width * 0.0667))
        margin_y = max(8, round(settings.height * 0.0873))
        window_x = margin_x
        window_y = margin_y
        window_width = settings.width - 2 * margin_x
        window_height = settings.height - 2 * margin_y
        title_bar_height = max(28, round(font_size * 2.9))

        padding = settings.padding
        usable_width = window_width - 2 * padding
        usable_height = window_height - title_bar_height - 2 * padding
        cols = usable_width // char_width
        rows = usable_height // line_height
        if cols < MIN_COLS or rows < MIN_ROWS:
            raise ValueError(
                f"image is too small for the font: {cols} by {rows} cells, "
                f"the minimum is {MIN_COLS} by {MIN_ROWS}"
            )
        cols = min(cols, MAX_COLS)
        rows = min(rows, MAX_ROWS)

        light_radius = max(4, round(font_size * 0.4))
        return cls(
            width=settings.width,
            height=settings.height,
            font_size=font_size,
            char_width=char_width,
            line_height=line_height,
            cols=cols,
            rows=rows,
            window_x=window_x,
            window_y=window_y,
            window_width=window_width,
            window_height=window_height,
            window_radius=10,
            backdrop_radius=18,
            title_bar_height=title_bar_height,
            light_radius=light_radius,
            light_x=window_x + round(title_bar_height * 0.545),
            light_y=window_y + title_bar_height // 2,
            light_gap=round(light_radius * 3.6),
            content_x=window_x + padding,
            content_top=window_y + title_bar_height + padding,
            baseline_offset=round((line_height + font_size * 0.72) / 2),
            cursor_width=char_width,
            cursor_height=round(font_size * 1.25),
            cursor_offset=font_size,
        )

    def baseline(self, line: int) -> int:
        """Return the baseline of a line, measured from the content top.

        Parameters
        ----------
        line : int
            Zero-based line index within the scrolling content.

        Returns
        -------
        int
            Offset in pixels below :attr:`content_top`.
        """
        return line * self.line_height + self.baseline_offset

    def column_x(self, column: int) -> int:
        """Return the left edge of a column, measured from the content left.

        Parameters
        ----------
        column : int
            Zero-based column index.

        Returns
        -------
        int
            Offset in pixels right of :attr:`content_x`.
        """
        return column * self.char_width
