"""Tests for the palette registry and its validation."""

from __future__ import annotations

import dataclasses
import unittest

from support import PtyReelTestCase

from ptyreel.theme import THEMES, Theme, resolve_theme


class RegistryTest(PtyReelTestCase):
    """Every shipped palette is complete and well formed."""

    def test_every_theme_validates(self) -> None:
        """Construction checks the values, so building each one proves them."""
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertEqual(theme.name, name)
                self.assertEqual(len(theme.ansi), 16)
                self.assertEqual(len(theme.traffic_lights), 3)

    def test_lookup_by_name(self) -> None:
        """A known name returns the palette itself."""
        self.assertIs(resolve_theme("github-dark"), THEMES["github-dark"])

    def test_unknown_name_lists_the_alternatives(self) -> None:
        """The message tells a tape author what they can use instead."""
        with self.assertRaises(KeyError) as caught:
            resolve_theme("dracula")
        self.assertIn("github-dark", str(caught.exception))


class ValidationTest(PtyReelTestCase):
    """A malformed palette cannot be built, so it cannot reach a document."""

    def base(self) -> Theme:
        """Return a palette to mutate in each case."""
        return THEMES["github-dark"]

    def test_bad_colours_are_rejected(self) -> None:
        """Anything but a six digit lower case hex value fails."""
        for colour in ("red", "#FFF", "#GGGGGG", "#ffffff ", "#FFFFFF", ""):
            with self.subTest(colour=colour):
                with self.assertRaises(ValueError):
                    dataclasses.replace(self.base(), background=colour)

    def test_bad_names_are_rejected(self) -> None:
        """A name reaches an error message, so it stays plain."""
        for name in ("Github Dark", "a/b", "", "x" * 33):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    dataclasses.replace(self.base(), name=name)

    def test_wrong_length_tuples_are_rejected(self) -> None:
        """A short palette would index out of range while rendering."""
        with self.assertRaises(ValueError):
            dataclasses.replace(self.base(), ansi=("#000000",) * 8)
        with self.assertRaises(ValueError):
            dataclasses.replace(self.base(), traffic_lights=("#000000",))


if __name__ == "__main__":
    unittest.main()
