"""Tests for key names and control character conversion."""

from __future__ import annotations

import unittest

from support import PtyReelTestCase

from ptyreel.keys import KEY_MAP, ctrl_code


class KeyMapTest(PtyReelTestCase):
    """Every key name maps to a sequence a terminal understands."""

    def test_names_are_upper_case(self) -> None:
        """Lookups are done on an upper cased name, so the table matches."""
        for name in KEY_MAP:
            with self.subTest(key=name):
                self.assertEqual(name, name.upper())

    def test_known_sequences(self) -> None:
        """The common keys send what a terminal expects."""
        expected = {
            "ENTER": "\r",
            "TAB": "\t",
            "BACKSPACE": "\x7f",
            "ESCAPE": "\x1b",
            "SPACE": " ",
            "UP": "\x1b[A",
            "DOWN": "\x1b[B",
            "RIGHT": "\x1b[C",
            "LEFT": "\x1b[D",
        }
        for name, sequence in expected.items():
            with self.subTest(key=name):
                self.assertEqual(KEY_MAP[name], sequence)

    def test_every_sequence_is_ascii(self) -> None:
        """A key sequence never needs multibyte encoding."""
        for name, sequence in KEY_MAP.items():
            with self.subTest(key=name):
                self.assertTrue(sequence.isascii())
                self.assertTrue(sequence)


class CtrlCodeTest(PtyReelTestCase):
    """Control combinations map onto the first twenty six code points."""

    def test_letters_map_to_control_characters(self) -> None:
        """Case does not matter and the range is complete."""
        for index in range(26):
            letter = chr(ord("a") + index)
            with self.subTest(letter=letter):
                self.assertEqual(ctrl_code(letter), chr(index + 1))
                self.assertEqual(ctrl_code(letter.upper()), chr(index + 1))

    def test_well_known_combinations(self) -> None:
        """Interrupt and clear are the two people recognise."""
        self.assertEqual(ctrl_code("c"), "\x03")
        self.assertEqual(ctrl_code("l"), "\x0c")

    def test_anything_but_one_letter_is_rejected(self) -> None:
        """A bad argument fails loudly rather than sending nothing."""
        for bad in ("", "ab", "1", "+", "é"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    ctrl_code(bad)


if __name__ == "__main__":
    unittest.main()
