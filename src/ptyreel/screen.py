"""A terminal screen that records when every character appeared.

The model is deliberately narrow. PtyReel animates scripted command sessions,
so it implements what a shell and ordinary command line programs emit, and
discards the rest without letting it corrupt the text around it. Anything not
listed below is consumed and ignored, which is the difference between an
unsupported sequence and a garbled line.

Implemented
    Printable text, tab, backspace, carriage return, newline. Cursor
    positioning by CUP, CUU, CUD, CUF, CUB, CHA and VPA. Erasing by EL and
    ED. Colour and text attributes by SGR.
Consumed and ignored
    Every other control sequence, including the private mode sets that turn
    on bracketed paste, the window title sequences the shell emits, device
    status requests, charset designators, and the extended colour forms of
    SGR 38 and 48. Background colour is parsed and dropped.

The screen never reads a clock. The caller passes the time with each call,
which is what lets a test drive the model with exact timestamps and what lets
the driver build a timeline from a tape's declared timing rather than from
whatever the machine happened to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from ptyreel.layout import MAX_LINES
from ptyreel.recording import NEVER, LineVersion, Recording, Style
from ptyreel.xmltext import is_storable

__all__ = ["MAX_PENDING", "MAX_STRING", "TAB_WIDTH", "TerminalScreen"]

MAX_PENDING: Final[int] = 256
MAX_STRING: Final[int] = 4_096
TAB_WIDTH: Final[int] = 8

_CSI_PARAMS: Final[str] = "0123456789;:<=>?"
_CSI_INTERMEDIATES: Final[str] = " !\"#$%&'()*+,-./"
_CHARSET_LEADERS: Final[str] = "()*+-./"
_STRING_LEADERS: Final[str] = "P^_X"
_BEL: Final[str] = "\x07"
_ESC: Final[str] = "\x1b"


@dataclass(slots=True)
class _LiveLine:
    """A line currently on screen, and when its cells were written."""

    birth_ms: int
    chars: list[str]
    styles: list[int]
    times: list[int]


@dataclass(slots=True)
class _Pen:
    """Mutable attribute state built up by SGR sequences."""

    fg: int | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    dim: bool = False

    def freeze(self) -> Style:
        """Return an immutable copy of the current attributes."""
        return Style(
            fg=self.fg,
            bold=self.bold,
            italic=self.italic,
            underline=self.underline,
            dim=self.dim,
        )

    def reset(self) -> None:
        """Return every attribute to its default."""
        self.fg = None
        self.bold = False
        self.italic = False
        self.underline = False
        self.dim = False


@dataclass(slots=True)
class TerminalScreen:
    """A grid of cells over an unbounded column of lines.

    Parameters
    ----------
    cols : int
        Width of the visible grid.
    rows : int
        Height of the visible grid.

    Attributes
    ----------
    cols, rows : int
        Size of the visible grid.
    """

    cols: int
    rows: int
    _top: int = field(default=0, init=False)
    _row: int = field(default=0, init=False)
    _col: int = field(default=0, init=False)
    _wrap_pending: bool = field(default=False, init=False)
    _now: int = field(default=0, init=False)
    _pending: str = field(default="", init=False)
    _pen: _Pen = field(default_factory=_Pen, init=False)
    _live: dict[int, _LiveLine] = field(default_factory=dict, init=False)
    _versions: list[LineVersion] = field(default_factory=list, init=False)
    _scrolls: list[tuple[int, int]] = field(default_factory=lambda: [(0, 0)], init=False)
    _cursors: list[tuple[int, int, int]] = field(
        default_factory=lambda: [(0, 0, 0)], init=False
    )
    _styles: list[Style] = field(default_factory=lambda: [Style()], init=False)
    _style_index: dict[Style, int] = field(default_factory=lambda: {Style(): 0}, init=False)
    _pen_id: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        """Reject a grid too small to hold anything."""
        if self.cols < 1 or self.rows < 1:
            raise ValueError(f"grid must be positive, got {self.cols} by {self.rows}")

    def feed(self, data: str, *, time_ms: int) -> None:
        r"""Apply terminal output to the screen at a fixed time.

        The stream is scanned once. Printable characters are written at the
        cursor and stamped with ``time_ms``. Control characters move the
        cursor. An ESC starts a sequence that is accumulated until its final
        character arrives.

        A sequence cut short by the end of ``data`` is held and resumed on
        the next call, so a sequence split across two reads still decodes as
        one sequence. The held text is bounded: a run longer than
        :data:`MAX_PENDING` without a final character, or a string sequence
        longer than :data:`MAX_STRING` without a terminator, is discarded and
        scanning returns to ordinary text.

        Erasing does not record a time. Cleared cells return to blank with
        time :data:`NEVER`, and the line they were on starts a new version,
        so the animation replaces the old text instead of layering new text
        on top of it.

        Parameters
        ----------
        data : str
            Decoded terminal output. May begin inside a sequence left
            pending by an earlier call, and may end inside one.
        time_ms : int
            Milliseconds since the session started, applied to every cell
            written during this call.

        Raises
        ------
        ValueError
            If ``time_ms`` runs backwards, or if the session has produced
            more than :data:`ptyreel.layout.MAX_LINES` lines.

        Examples
        --------
        >>> screen = TerminalScreen(cols=8, rows=2)
        >>> screen.feed("\x1b[31mred", time_ms=100)
        >>> screen.snapshot().lines[0].chars
        'red     '
        """
        if time_ms < self._now:
            raise ValueError(f"time went backwards: {time_ms} after {self._now}")
        self._now = time_ms
        buffer = self._pending + data
        self._pending = ""
        index = 0
        size = len(buffer)
        while index < size:
            char = buffer[index]
            if char == _ESC:
                consumed = self._scan_escape(buffer, index)
                if consumed is None:
                    remainder = buffer[index:]
                    limit = MAX_STRING if self._is_string_start(remainder) else MAX_PENDING
                    if len(remainder) <= limit:
                        self._pending = remainder
                    break
                index = consumed
            elif char < " " or char == "\x7f":
                self._control(char)
                index += 1
            else:
                self._put(char)
                index += 1
        self._record_cursor()

    def _record_cursor(self) -> None:
        """Append the cursor position to its track when it has moved."""
        where = (self._now, self._top + self._row, min(self._col, self.cols - 1))
        last = self._cursors[-1]
        if last[1:] == where[1:]:
            return
        if last[0] == where[0]:
            self._cursors[-1] = where
            return
        self._cursors.append(where)

    def snapshot(self, *, duration_ms: int | None = None) -> Recording:
        """Return the session so far as an immutable value.

        The screen is not modified, so a caller may take a snapshot at any
        point and keep feeding afterwards.

        Parameters
        ----------
        duration_ms : int or None, optional
            Length of the timeline. Defaults to the time of the last feed.
            Must not be earlier than that.

        Returns
        -------
        Recording
            Every version of every line, the scroll track, and the final
            cursor position.

        Raises
        ------
        ValueError
            If ``duration_ms`` is earlier than the last recorded event.
        """
        end = self._now if duration_ms is None else duration_ms
        if end < self._now:
            raise ValueError(f"duration {end} is before the last event {self._now}")
        versions = list(self._versions)
        for index in sorted(self._live):
            versions.append(self._freeze(index, self._live[index], NEVER))
        versions.sort(key=lambda version: (version.birth_ms, version.line))
        return Recording(
            cols=self.cols,
            rows=self.rows,
            duration_ms=end,
            styles=tuple(self._styles),
            lines=tuple(versions),
            scrolls=tuple(self._scrolls),
            cursors=tuple(self._cursors),
        )

    def _is_string_start(self, remainder: str) -> bool:
        """Report whether held text begins a sequence with a long payload."""
        return len(remainder) > 1 and (
            remainder[1] == "]" or remainder[1] in _STRING_LEADERS
        )

    def _line(self, index: int) -> _LiveLine:
        """Return the live line at an absolute index, creating it if needed."""
        line = self._live.get(index)
        if line is None:
            if index >= MAX_LINES:
                raise ValueError(f"session produced more than {MAX_LINES} lines")
            line = _LiveLine(
                birth_ms=self._now,
                chars=[" "] * self.cols,
                styles=[0] * self.cols,
                times=[NEVER] * self.cols,
            )
            self._live[index] = line
        return line

    def _freeze(self, index: int, line: _LiveLine, death_ms: int) -> LineVersion:
        """Turn a live line into an immutable version."""
        return LineVersion(
            line=index,
            birth_ms=line.birth_ms,
            death_ms=death_ms,
            chars="".join(line.chars),
            styles=tuple(line.styles),
            times=tuple(line.times),
        )

    def _fork(self, index: int) -> _LiveLine:
        """Close the current version of a line and open a replacement.

        Content carries over so a partial rewrite keeps the text it did not
        touch, but every carried cell is restamped with the current time.
        The old version dies at the same instant the new one is born, so the
        line does not blink.

        A line forks at most once per instant. A redraw overwrites many cells
        in a row, and every one of them is a reason to fork, but they all
        belong to the same replacement.
        """
        line = self._live[index]
        if line.birth_ms == self._now:
            return line
        self._versions.append(self._freeze(index, line, self._now))
        replacement = _LiveLine(
            birth_ms=self._now,
            chars=list(line.chars),
            styles=list(line.styles),
            times=[self._now if stamp != NEVER else NEVER for stamp in line.times],
        )
        self._live[index] = replacement
        return replacement

    def _style_id(self) -> int:
        """Return the table index of the pen's current style."""
        return self._pen_id

    def _intern(self) -> None:
        """Record the pen's style in the table and cache its index."""
        style = self._pen.freeze()
        found = self._style_index.get(style)
        if found is None:
            found = len(self._styles)
            self._styles.append(style)
            self._style_index[style] = found
        self._pen_id = found

    def _put(self, char: str) -> None:
        """Write one printable character at the cursor."""
        if not is_storable(char):
            return
        if self._wrap_pending:
            self._wrap_pending = False
            self._col = 0
            self._newline()
        index = self._top + self._row
        line = self._line(index)
        column = self._col
        style = self._style_id()
        if line.times[column] != NEVER and (
            line.chars[column] != char or line.styles[column] != style
        ):
            line = self._fork(index)
        line.chars[column] = char
        line.styles[column] = style
        line.times[column] = self._now
        if column + 1 >= self.cols:
            self._wrap_pending = True
        else:
            self._col = column + 1

    def _control(self, char: str) -> None:
        """Apply a C0 control character."""
        if char == "\n":
            self._wrap_pending = False
            self._newline()
        elif char == "\r":
            self._wrap_pending = False
            self._col = 0
        elif char == "\b":
            self._wrap_pending = False
            self._col = max(0, self._col - 1)
        elif char == "\t":
            self._wrap_pending = False
            target = min(self.cols - 1, (self._col // TAB_WIDTH + 1) * TAB_WIDTH)
            self._col = target

    def _newline(self) -> None:
        """Move down one line, scrolling the window when at the bottom."""
        if self._row + 1 < self.rows:
            self._row += 1
        else:
            self._top += 1
            self._record_scroll()
        self._line(self._top + self._row)

    def _record_scroll(self) -> None:
        """Append the window position to the scroll track."""
        if self._scrolls and self._scrolls[-1][0] == self._now:
            self._scrolls[-1] = (self._now, self._top)
        else:
            self._scrolls.append((self._now, self._top))

    def _erase(self, index: int, start: int, stop: int) -> None:
        """Blank a span of one line, forking it when anything was visible."""
        line = self._live.get(index)
        if line is None:
            return
        if not any(line.times[position] != NEVER for position in range(start, stop)):
            return
        line = self._fork(index)
        for position in range(start, stop):
            line.chars[position] = " "
            line.styles[position] = 0
            line.times[position] = NEVER

    def _scan_escape(self, buffer: str, start: int) -> int | None:
        """Consume one escape sequence, returning the index after it."""
        size = len(buffer)
        if start + 1 >= size:
            return None
        leader = buffer[start + 1]
        if leader == "[":
            return self._scan_csi(buffer, start)
        if leader == "]" or leader in _STRING_LEADERS:
            return self._scan_string(buffer, start)
        if leader in _CHARSET_LEADERS:
            return None if start + 2 >= size else start + 3
        if leader == "M":
            self._reverse_index()
            return start + 2
        return start + 2

    def _scan_csi(self, buffer: str, start: int) -> int | None:
        """Consume a control sequence and apply it if it is supported."""
        size = len(buffer)
        cursor = start + 2
        while cursor < size and buffer[cursor] in _CSI_PARAMS:
            cursor += 1
        while cursor < size and buffer[cursor] in _CSI_INTERMEDIATES:
            cursor += 1
        if cursor >= size:
            return None
        final = buffer[cursor]
        if not "\x40" <= final <= "\x7e":
            return cursor + 1
        body = buffer[start + 2 : cursor]
        if not body.startswith("?"):
            self._apply_csi(body, final)
        return cursor + 1

    def _scan_string(self, buffer: str, start: int) -> int | None:
        """Consume an operating system or device control string."""
        cursor = start + 2
        size = len(buffer)
        while cursor < size:
            char = buffer[cursor]
            if char == _BEL:
                return cursor + 1
            if char == _ESC:
                if cursor + 1 >= size:
                    return None
                if buffer[cursor + 1] == "\\":
                    return cursor + 2
                return cursor + 1
            cursor += 1
        return None

    def _apply_csi(self, body: str, final: str) -> None:
        """Dispatch a supported control sequence."""
        if final == "m":
            self._apply_sgr(body)
            return
        params = [part for part in body.split(";")]
        first = self._number(params, 0, 1)
        if final in "Hf":
            row = self._number(params, 0, 1) - 1
            column = self._number(params, 1, 1) - 1
            self._row = max(0, min(self.rows - 1, row))
            self._col = max(0, min(self.cols - 1, column))
            self._wrap_pending = False
        elif final == "A":
            self._row = max(0, self._row - first)
            self._wrap_pending = False
        elif final == "B":
            self._row = min(self.rows - 1, self._row + first)
            self._wrap_pending = False
        elif final == "C":
            self._col = min(self.cols - 1, self._col + first)
            self._wrap_pending = False
        elif final == "D":
            self._col = max(0, self._col - first)
            self._wrap_pending = False
        elif final in "G`":
            self._col = max(0, min(self.cols - 1, first - 1))
            self._wrap_pending = False
        elif final == "d":
            self._row = max(0, min(self.rows - 1, first - 1))
            self._wrap_pending = False
        elif final == "K":
            self._erase_in_line(self._number(params, 0, 0))
        elif final == "J":
            self._erase_in_display(self._number(params, 0, 0))

    def _erase_in_line(self, mode: int) -> None:
        """Blank part of the cursor's line."""
        index = self._top + self._row
        if mode == 0:
            self._erase(index, self._col, self.cols)
        elif mode == 1:
            self._erase(index, 0, min(self._col + 1, self.cols))
        elif mode == 2:
            self._erase(index, 0, self.cols)

    def _erase_in_display(self, mode: int) -> None:
        """Blank part of the visible window."""
        index = self._top + self._row
        if mode == 0:
            self._erase(index, self._col, self.cols)
            for row in range(self._row + 1, self.rows):
                self._erase(self._top + row, 0, self.cols)
        elif mode == 1:
            for row in range(0, self._row):
                self._erase(self._top + row, 0, self.cols)
            self._erase(index, 0, min(self._col + 1, self.cols))
        elif mode in (2, 3):
            for row in range(self.rows):
                self._erase(self._top + row, 0, self.cols)

    def _reverse_index(self) -> None:
        """Move up one line, staying inside the window."""
        self._wrap_pending = False
        if self._row > 0:
            self._row -= 1

    def _apply_sgr(self, body: str) -> None:
        """Update the pen from a select graphic rendition sequence."""
        if not body:
            self._pen.reset()
            self._intern()
            return
        params = body.split(";")
        position = 0
        while position < len(params):
            raw = params[position]
            if ":" in raw:
                position += 1
                continue
            code = self._number(params, position, 0)
            if code in (38, 48):
                position += self._skip_extended(params, position)
                continue
            self._apply_sgr_code(code)
            position += 1
        self._intern()

    def _apply_sgr_code(self, code: int) -> None:
        """Apply one select graphic rendition parameter."""
        pen = self._pen
        if code == 0:
            pen.reset()
        elif code == 1:
            pen.bold = True
        elif code == 2:
            pen.dim = True
        elif code == 3:
            pen.italic = True
        elif code == 4:
            pen.underline = True
        elif code == 22:
            pen.bold = False
            pen.dim = False
        elif code == 23:
            pen.italic = False
        elif code == 24:
            pen.underline = False
        elif 30 <= code <= 37:
            pen.fg = code - 30
        elif code == 39:
            pen.fg = None
        elif 90 <= code <= 97:
            pen.fg = code - 90 + 8

    def _skip_extended(self, params: list[str], position: int) -> int:
        """Return how many parameters an extended colour spec occupies."""
        selector = self._number(params, position + 1, -1)
        if selector == 5:
            return 3
        if selector == 2:
            return 5
        return 1

    @staticmethod
    def _number(params: list[str], index: int, default: int) -> int:
        """Read one numeric parameter, falling back to a default."""
        if index >= len(params):
            return default
        raw = params[index]
        if not raw or not raw.isdigit():
            return default
        return int(raw)
