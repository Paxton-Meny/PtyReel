"""Tests for the terminal screen model.

Each case feeds a byte string and asserts the text that ends up on screen.
Times are always passed in, never measured, so the same input always gives the
same recording.
"""

from __future__ import annotations

import unittest

from support import PtyReelTestCase, dump

from ptyreel.recording import NEVER
from ptyreel.screen import TerminalScreen

SCREEN_CASES: tuple[tuple[str, int, int, str, str], ...] = (
    ("plain", 8, 2, "abc", "abc"),
    ("carriage_return", 8, 2, "abc\rX", "Xbc"),
    ("backspace", 8, 2, "ab\b\bX", "Xb"),
    ("backspace_at_start", 8, 2, "\bX", "X"),
    ("tab", 16, 2, "a\tb", "a       b"),
    ("tab_from_stop", 24, 2, "12345678\tX", "12345678        X"),
    ("tab_clamps", 8, 2, "1234567\tX", "1234567X"),
    ("bell_ignored", 8, 2, "a\x07b", "ab"),
    ("nulls_ignored", 8, 2, "a\x00\x01b", "ab"),
    ("delete_ignored", 8, 2, "a\x7fb", "ab"),
    ("wrap", 4, 3, "abcdef", "abcd\nef"),
    ("newline_with_return", 4, 3, "ab\r\ncd", "ab\ncd"),
    ("bare_newline_keeps_column", 4, 3, "abc\nd", "abc\n   d"),
    ("osc_bel_consumed", 8, 2, "\x1b]0;title\x07X", "X"),
    ("osc_st_consumed", 8, 2, "\x1b]0;title\x1b\\X", "X"),
    ("private_mode_consumed", 8, 2, "\x1b[?2004hA\x1b[?2004l", "A"),
    ("charset_consumed", 8, 2, "\x1b(BA", "A"),
    ("device_query_consumed", 8, 2, "\x1b[6nA", "A"),
    ("cursor_position", 8, 3, "\x1b[2;3HX", "\n  X"),
    ("cursor_home", 8, 3, "abc\x1b[HX", "Xbc"),
    ("cursor_clamps", 4, 2, "\x1b[99;99HX", "\n   X"),
    ("cursor_forward_clamps", 4, 2, "\x1b[9CX", "   X"),
    ("erase_to_end", 8, 2, "abcd\x1b[2D\x1b[0KX", "abX"),
    ("erase_to_start", 8, 2, "abcd\x1b[1KX", "    X"),
    ("erase_line", 8, 2, "abcd\x1b[2KX", "    X"),
    ("erase_display", 8, 2, "abc\x1b[2J", ""),
    ("column_absolute", 8, 2, "abcd\x1b[2GX", "aXcd"),
    ("row_absolute", 8, 3, "\x1b[3dX", "\n\nX"),
    ("indexed_colour_text_survives", 8, 2, "\x1b[38;5;196mRED\x1b[0m", "RED"),
    ("true_colour_text_survives", 8, 2, "\x1b[38;2;255;0;0mR", "R"),
    ("background_dropped", 8, 2, "\x1b[48;5;21mX", "X"),
    ("colon_form_ignored", 8, 2, "\x1b[38:5:9mX", "X"),
)


class ScreenTest(PtyReelTestCase):
    """Text, control characters and sequences land where they should."""

    def screen(self, cols: int, rows: int, text: str) -> TerminalScreen:
        """Feed a whole string to a fresh screen at one instant."""
        screen = TerminalScreen(cols=cols, rows=rows)
        screen.feed(text, time_ms=10)
        return screen

    def test_cases(self) -> None:
        """Each input produces the expected final screen."""
        for name, cols, rows, text, expected in SCREEN_CASES:
            with self.subTest(case=name):
                recording = self.screen(cols, rows, text).snapshot()
                self.assertEqual(dump(recording), expected)

    def test_scrolling_keeps_the_last_rows(self) -> None:
        """Writing past the bottom moves the window, it does not lose text."""
        recording = self.screen(4, 2, "ab\r\ncd\r\nef").snapshot()
        self.assertEqual(dump(recording), "ab\ncd\nef")
        self.assertEqual(recording.scrolls[-1][1], 1)

    def test_scroll_track_records_each_step(self) -> None:
        """The window position is recorded whenever it moves."""
        screen = TerminalScreen(cols=4, rows=2)
        screen.feed("a\n", time_ms=0)
        screen.feed("b\n", time_ms=100)
        screen.feed("c\n", time_ms=200)
        recording = screen.snapshot()
        self.assertEqual(recording.scrolls, ((0, 0), (100, 1), (200, 2)))

    def test_deferred_wrap(self) -> None:
        """Filling the last column does not move to the next line by itself."""
        recording = self.screen(4, 3, "abcd\rX").snapshot()
        self.assertEqual(dump(recording), "Xbcd")


class VersionTest(PtyReelTestCase):
    """Rewriting a line replaces it instead of drawing over it."""

    def test_overwrite_starts_a_new_version(self) -> None:
        """A progress redraw produces two versions of one line."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("50%", time_ms=0)
        screen.feed("\r75%", time_ms=500)
        recording = screen.snapshot()
        versions = [version for version in recording.lines if version.line == 0]
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].chars.rstrip(), "50%")
        self.assertEqual(versions[0].death_ms, 500)
        self.assertEqual(versions[1].chars.rstrip(), "75%")
        self.assertEqual(versions[1].birth_ms, 500)
        self.assertEqual(versions[1].death_ms, NEVER)

    def test_identical_redraw_does_not_fork(self) -> None:
        """Drawing the same text again is not a change, so nothing forks."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("abc", time_ms=0)
        screen.feed("\rabc", time_ms=500)
        self.assertEqual(len(screen.snapshot().lines), 1)

    def test_erase_starts_a_new_version(self) -> None:
        """Cleared text disappears rather than staying underneath."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("abc", time_ms=0)
        screen.feed("\r\x1b[2K", time_ms=400)
        recording = screen.snapshot()
        self.assertEqual(len(recording.lines), 2)
        self.assertEqual(recording.lines[0].death_ms, 400)
        self.assertEqual(dump(recording), "")

    def test_erase_of_blank_line_does_nothing(self) -> None:
        """Clearing a line nothing was written to is not a change."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("\x1b[2K", time_ms=0)
        self.assertEqual(screen.snapshot().lines, ())

    def test_carried_text_is_restamped(self) -> None:
        """Text a new version inherits appears when that version does."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("abcd", time_ms=0)
        screen.feed("\rX", time_ms=600)
        latest = screen.snapshot().lines[-1]
        self.assertEqual(latest.chars.rstrip(), "Xbcd")
        self.assertEqual(latest.times[:4], (600, 600, 600, 600))


class StyleTest(PtyReelTestCase):
    """Attributes are tracked per cell through a shared table."""

    def styles(self, text: str) -> list[object]:
        """Return the style of each written cell of the first line."""
        screen = TerminalScreen(cols=16, rows=2)
        screen.feed(text, time_ms=0)
        recording = screen.snapshot()
        version = recording.lines[0]
        return [
            recording.styles[version.styles[column]]
            for column in range(len(version.chars))
            if version.times[column] != NEVER
        ]

    def test_style_table_starts_with_the_default(self) -> None:
        """Index zero always means plain text."""
        screen = TerminalScreen(cols=4, rows=2)
        screen.feed("a", time_ms=0)
        recording = screen.snapshot()
        self.assertEqual(recording.styles[0].fg, None)
        self.assertFalse(recording.styles[0].bold)

    def test_attributes(self) -> None:
        """Each supported attribute turns on and off again."""
        cases = (
            ("\x1b[1;31mA\x1b[0mB", (True, 1), (False, None)),
            ("\x1b[91mA\x1b[0mB", (False, 9), (False, None)),
            ("\x1b[31mA\x1b[39mB", (False, 1), (False, None)),
            ("\x1b[1mA\x1b[22mB", (True, None), (False, None)),
            ("\x1b[mA\x1b[31mB", (False, None), (False, 1)),
        )
        for text, first, second in cases:
            with self.subTest(text=text):
                styles = self.styles(text)
                self.assertEqual((styles[0].bold, styles[0].fg), first)
                self.assertEqual((styles[1].bold, styles[1].fg), second)

    def test_italic_and_underline(self) -> None:
        """Both toggle independently."""
        styles = self.styles("\x1b[3mA\x1b[23m\x1b[4mB\x1b[24mC")
        self.assertTrue(styles[0].italic)
        self.assertTrue(styles[1].underline)
        self.assertFalse(styles[2].italic)
        self.assertFalse(styles[2].underline)


class TornInputTest(PtyReelTestCase):
    """A sequence split across two reads still decodes as one sequence."""

    def test_split_control_sequence(self) -> None:
        """Half a colour code followed by its other half still colours."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("\x1b[3", time_ms=0)
        screen.feed("1mA", time_ms=10)
        recording = screen.snapshot()
        self.assertEqual(dump(recording), "A")
        self.assertEqual(recording.styles[recording.lines[0].styles[0]].fg, 1)

    def test_split_escape_lead(self) -> None:
        """A lone escape at the end of a read waits for its partner."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("\x1b", time_ms=0)
        screen.feed("]0;t\x07X", time_ms=10)
        self.assertEqual(dump(screen.snapshot()), "X")

    def test_split_string_sequence(self) -> None:
        """A title sequence spanning two reads is still swallowed whole."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("\x1b]0;some ti", time_ms=0)
        screen.feed("tle\x07X", time_ms=10)
        self.assertEqual(dump(screen.snapshot()), "X")

    def test_unterminated_sequence_is_dropped(self) -> None:
        """An endless sequence cannot grow the pending buffer for ever."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("\x1b[" + "1;" * 500, time_ms=0)
        screen.feed("X", time_ms=10)
        self.assertEqual(dump(screen.snapshot()), "X")


class ClockTest(PtyReelTestCase):
    """The screen never reads a clock, and refuses one that goes backwards."""

    def test_time_must_not_go_backwards(self) -> None:
        """Reveal buckets are ordered, so time has to be too."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("a", time_ms=100)
        with self.assertRaises(ValueError):
            screen.feed("b", time_ms=50)

    def test_snapshot_does_not_disturb_the_screen(self) -> None:
        """A snapshot can be taken at any point without ending the session."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("ab", time_ms=0)
        first = screen.snapshot()
        screen.feed("c", time_ms=10)
        second = screen.snapshot()
        self.assertEqual(dump(first), "ab")
        self.assertEqual(dump(second), "abc")

    def test_duration_must_cover_the_session(self) -> None:
        """A timeline cannot end before the last thing that happened."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("a", time_ms=100)
        with self.assertRaises(ValueError):
            screen.snapshot(duration_ms=50)

    def test_cursor_track_follows_the_writing(self) -> None:
        """Each move is recorded so the cursor can be animated."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("a", time_ms=0)
        screen.feed("b", time_ms=100)
        screen.feed("\r\n", time_ms=200)
        self.assertEqual(
            screen.snapshot().cursors, ((0, 0, 1), (100, 0, 2), (200, 1, 0))
        )


if __name__ == "__main__":
    unittest.main()
