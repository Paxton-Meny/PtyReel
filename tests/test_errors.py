"""Tests for the exception hierarchy and its message format."""

from __future__ import annotations

import unittest

from support import PtyReelTestCase

from ptyreel.errors import (
    DriverError,
    PathSecurityError,
    PtyReelError,
    RenderError,
    TapeError,
)


class TapeErrorTest(PtyReelTestCase):
    """A tape error reads like a compiler diagnostic."""

    def test_message_carries_file_and_line(self) -> None:
        """A located error prefixes the file and the line."""
        error = TapeError("unknown directive: Wat", source="demo.tape", line=4)
        self.assertEqual(str(error), "demo.tape:4: unknown directive: Wat")
        self.assertEqual(error.line, 4)
        self.assertEqual(error.source, "demo.tape")
        self.assertEqual(error.message, "unknown directive: Wat")

    def test_message_without_a_line_names_only_the_file(self) -> None:
        """A whole-file problem still names the file."""
        error = TapeError("no Output directive", source="demo.tape")
        self.assertEqual(str(error), "demo.tape: no Output directive")
        self.assertIsNone(error.line)

    def test_path_error_appends_the_path(self) -> None:
        """A path error shows the offending path after the message."""
        error = PathSecurityError(
            "path is absolute", source="demo.tape", line=2, path="/etc/x.svg"
        )
        self.assertEqual(str(error), "demo.tape:2: path is absolute: /etc/x.svg")
        self.assertEqual(error.path, "/etc/x.svg")


class HierarchyTest(PtyReelTestCase):
    """Every error the package raises shares one base class."""

    def test_every_error_derives_from_the_base(self) -> None:
        """One except clause is enough to catch anything expected."""
        for error in (TapeError, PathSecurityError, DriverError, RenderError):
            with self.subTest(error=error.__name__):
                self.assertTrue(issubclass(error, PtyReelError))

    def test_a_path_error_is_a_tape_error(self) -> None:
        """Path problems carry a location, so they are tape errors."""
        self.assertTrue(issubclass(PathSecurityError, TapeError))


if __name__ == "__main__":
    unittest.main()
