"""Tests for the geometry derived from a tape's settings."""

from __future__ import annotations

import dataclasses
import unittest

from support import PtyReelTestCase

from ptyreel.layout import MAX_COLS, MAX_ROWS, MIN_COLS, MIN_ROWS, Layout
from ptyreel.tape import TapeSettings


class LayoutTest(PtyReelTestCase):
    """One layout answers every geometry question in the renderer."""

    def layout(self, **changes: object) -> Layout:
        """Build a layout from the defaults plus some changes."""
        return Layout.from_settings(dataclasses.replace(TapeSettings(), **changes))

    def test_defaults(self) -> None:
        """The default size gives a workable grid."""
        layout = self.layout()
        self.assertEqual(layout.char_width, 9)
        self.assertEqual(layout.line_height, 24)
        self.assertGreaterEqual(layout.cols, MIN_COLS)
        self.assertGreaterEqual(layout.rows, MIN_ROWS)

    def test_window_sits_inside_the_image(self) -> None:
        """Nothing is drawn outside the canvas."""
        for width, height in ((320, 200), (900, 550), (1600, 900), (4096, 4096)):
            with self.subTest(size=(width, height)):
                layout = self.layout(width=width, height=height, font_size=12)
                self.assertGreater(layout.window_x, 0)
                self.assertGreater(layout.window_y, 0)
                self.assertLessEqual(layout.window_x + layout.window_width, width)
                self.assertLessEqual(layout.window_y + layout.window_height, height)

    def test_grid_is_clamped(self) -> None:
        """A very large image cannot ask for an unbounded terminal."""
        layout = self.layout(width=4096, height=4096, font_size=8, padding=0)
        self.assertLessEqual(layout.cols, MAX_COLS)
        self.assertLessEqual(layout.rows, MAX_ROWS)

    def test_too_small_is_refused(self) -> None:
        """A large font in a small window fails rather than rendering badly."""
        with self.assertRaises(ValueError) as caught:
            self.layout(width=320, height=200, font_size=40)
        self.assertIn("too small", str(caught.exception))

    def test_content_starts_below_the_title_bar(self) -> None:
        """Text never overlaps the window controls."""
        layout = self.layout()
        self.assertGreaterEqual(
            layout.content_top, layout.window_y + layout.title_bar_height
        )

    def test_positions_are_linear(self) -> None:
        """Columns and lines are evenly spaced, which the renderer assumes."""
        layout = self.layout()
        self.assertEqual(layout.column_x(0), 0)
        self.assertEqual(layout.column_x(10), 10 * layout.char_width)
        self.assertEqual(
            layout.baseline(3) - layout.baseline(2), layout.line_height
        )

    def test_traffic_lights_fit_the_bar(self) -> None:
        """Three controls sit inside the title bar at every size."""
        for font_size in (8, 15, 24, 40):
            with self.subTest(font_size=font_size):
                layout = self.layout(width=1600, height=1200, font_size=font_size)
                top = layout.light_y - layout.light_radius
                bottom = layout.light_y + layout.light_radius
                self.assertGreater(top, layout.window_y)
                self.assertLess(bottom, layout.window_y + layout.title_bar_height)


if __name__ == "__main__":
    unittest.main()
