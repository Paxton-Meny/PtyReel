"""The frozen result of a capture, and the seam that makes rendering testable.

Everything upstream of a :class:`Recording` talks to a real pseudo-terminal
and a real clock. Everything downstream is a pure function of this value. A
test can therefore build a recording by hand and assert on the exact bytes the
renderer produces, with no terminal involved.

The model is a stream of lines, not a fixed screen. Output is written into an
unbounded column of lines addressed by absolute index, and the visible window
slides down that column as the session scrolls. Scrolling is a movement of the
window, recorded in :attr:`Recording.scrolls`, so text never has to be redrawn
at a new position just because the screen moved.

A line can be rewritten in place, by a carriage return, by an erase, or by a
program that moves the cursor back. Each rewrite closes the current
:class:`LineVersion` and opens a new one at the same index, so the animation
shows the replacement instead of showing both at once. Within one version,
each cell carries the time it was written, which is what produces the effect
of text appearing as it was typed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

__all__ = ["NEVER", "LineVersion", "Recording", "Style"]

NEVER: Final[int] = -1


@dataclass(frozen=True, slots=True)
class Style:
    """Visual attributes of a run of characters.

    Attributes
    ----------
    fg : int or None
        Index into a theme's sixteen colours, or ``None`` for the default
        foreground.
    bold, italic, underline, dim : bool
        Whether the matching attribute is set.
    """

    fg: int | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    dim: bool = False


@dataclass(frozen=True, slots=True)
class LineVersion:
    """One rendering of one line, alive for a span of the timeline.

    Attributes
    ----------
    line : int
        Absolute line index in the scrolling document.
    birth_ms : int
        When this version starts being shown.
    death_ms : int
        When it stops being shown, or :data:`NEVER` if it survives to the
        end of the session.
    chars : str
        Exactly ``cols`` characters. Cells never written hold a space.
    styles : tuple of int
        One index into :attr:`Recording.styles` per cell.
    times : tuple of int
        When each cell appears, or :data:`NEVER` for a cell that is blank
        and should never be drawn.
    """

    line: int
    birth_ms: int
    death_ms: int
    chars: str
    styles: tuple[int, ...]
    times: tuple[int, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class Recording:
    """A complete captured session.

    Attributes
    ----------
    cols, rows : int
        Size of the visible grid.
    duration_ms : int
        Length of the timeline. Every time in the recording falls inside it.
    styles : tuple of Style
        Style table. Index zero is always the default style.
    lines : tuple of LineVersion
        Every version of every line, ordered by birth then by line index.
    scrolls : tuple
        Pairs of time and the absolute index of the top visible line. The
        first pair is always at time zero. A session that scrolls before it
        prints anything starts partway down.
    cursors : tuple
        Triples of time, absolute line and column, tracking where the
        cursor sat through the session. The first triple is always at time
        zero. Animating this is what makes typing look typed.

    Raises
    ------
    ValueError
        If any invariant is broken. The renderer relies on all of them, so
        they are checked once here rather than defended against repeatedly.
    """

    cols: int
    rows: int
    duration_ms: int
    styles: tuple[Style, ...]
    lines: tuple[LineVersion, ...]
    scrolls: tuple[tuple[int, int], ...]
    cursors: tuple[tuple[int, int, int], ...]

    def __post_init__(self) -> None:
        """Check every invariant the renderer depends on."""
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"grid must be positive, got {self.cols} by {self.rows}")
        if self.duration_ms < 0:
            raise ValueError(f"duration must not be negative, got {self.duration_ms}")
        if not self.styles or self.styles[0] != Style():
            raise ValueError("style table must start with the default style")
        if not self.scrolls or self.scrolls[0][0] != 0:
            raise ValueError("scroll track must start at time zero")
        if not self.cursors or self.cursors[0][0] != 0:
            raise ValueError("cursor track must start at time zero")
        previous_time = -1
        for time_ms, top in self.scrolls:
            if not 0 <= time_ms <= self.duration_ms:
                raise ValueError(f"scroll time out of range: {time_ms}")
            if time_ms < previous_time:
                raise ValueError("scroll track must not go backwards in time")
            if top < 0:
                raise ValueError(f"scroll top must not be negative, got {top}")
            previous_time = time_ms
        previous_time = -1
        for time_ms, line, column in self.cursors:
            if not 0 <= time_ms <= self.duration_ms:
                raise ValueError(f"cursor time out of range: {time_ms}")
            if time_ms < previous_time:
                raise ValueError("cursor track must not go backwards in time")
            if line < 0 or not 0 <= column <= self.cols:
                raise ValueError(f"cursor is outside the document: {line}, {column}")
            previous_time = time_ms
        limit = len(self.styles)
        for version in self.lines:
            if version.line < 0:
                raise ValueError(f"line index must not be negative, got {version.line}")
            if len(version.chars) != self.cols:
                raise ValueError(
                    f"line {version.line} holds {len(version.chars)} cells, "
                    f"expected {self.cols}"
                )
            if len(version.styles) != self.cols or len(version.times) != self.cols:
                raise ValueError(f"line {version.line} has ragged cell data")
            if not 0 <= version.birth_ms <= self.duration_ms:
                raise ValueError(f"birth out of range on line {version.line}")
            if version.death_ms != NEVER and not (
                version.birth_ms <= version.death_ms <= self.duration_ms
            ):
                raise ValueError(f"death out of range on line {version.line}")
            if version.styles and max(version.styles) >= limit:
                raise ValueError(f"style index out of range on line {version.line}")
            if min(version.styles, default=0) < 0:
                raise ValueError(f"style index out of range on line {version.line}")
            for cell_time in version.times:
                if cell_time != NEVER and not 0 <= cell_time <= self.duration_ms:
                    raise ValueError(f"cell time out of range on line {version.line}")

    @property
    def line_count(self) -> int:
        """Return how many lines the document holds, including scrolled ones."""
        return max((version.line for version in self.lines), default=0) + 1

    def to_dict(self) -> dict[str, Any]:
        """Return a plain data form suitable for a test fixture.

        Returns
        -------
        dict
            Nested lists and dictionaries only, so the value survives a JSON
            round trip unchanged.
        """
        return {
            "cols": self.cols,
            "rows": self.rows,
            "duration_ms": self.duration_ms,
            "styles": [
                {
                    "fg": style.fg,
                    "bold": style.bold,
                    "italic": style.italic,
                    "underline": style.underline,
                    "dim": style.dim,
                }
                for style in self.styles
            ],
            "lines": [
                {
                    "line": version.line,
                    "birth_ms": version.birth_ms,
                    "death_ms": version.death_ms,
                    "chars": version.chars,
                    "styles": list(version.styles),
                    "times": list(version.times),
                }
                for version in self.lines
            ],
            "scrolls": [list(pair) for pair in self.scrolls],
            "cursors": [list(triple) for triple in self.cursors],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recording:
        """Rebuild a recording from :meth:`to_dict` output.

        Parameters
        ----------
        data : dict
            A mapping in the shape :meth:`to_dict` produces.

        Returns
        -------
        Recording
            The rebuilt value, validated the same way as any other.
        """
        return cls(
            cols=data["cols"],
            rows=data["rows"],
            duration_ms=data["duration_ms"],
            styles=tuple(Style(**style) for style in data["styles"]),
            lines=tuple(
                LineVersion(
                    line=version["line"],
                    birth_ms=version["birth_ms"],
                    death_ms=version["death_ms"],
                    chars=version["chars"],
                    styles=tuple(version["styles"]),
                    times=tuple(version["times"]),
                )
                for version in data["lines"]
            ),
            scrolls=tuple((pair[0], pair[1]) for pair in data["scrolls"]),
            cursors=tuple(
                (triple[0], triple[1], triple[2]) for triple in data["cursors"]
            ),
        )
