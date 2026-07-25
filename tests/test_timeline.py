"""Tests for animation naming and percentage arithmetic."""

from __future__ import annotations

import unittest

from support import PtyReelTestCase

from fixtures import COLS, line

from ptyreel.errors import RenderError
from ptyreel.recording import NEVER, Recording, Style
from ptyreel.timeline import BUCKET_MS, MAX_ANIMATIONS, build_timeline


def recording(**changes: object) -> Recording:
    """Build a small recording for timeline questions."""
    base = {
        "cols": COLS,
        "rows": 3,
        "duration_ms": 1_000,
        "styles": (Style(),),
        "lines": (line(0, "ab", start_ms=0, step_ms=500),),
        "scrolls": ((0, 0),),
        "cursors": ((0, 0, 0),),
    }
    base.update(changes)
    return Recording(**base)


class CycleTest(PtyReelTestCase):
    """One cycle covers the session and the rest before a replay."""

    def test_loop_adds_the_rest(self) -> None:
        """The pause is part of the cycle, so the loop stays in step."""
        timeline = build_timeline(recording(), loop=True, loop_delay_ms=2_000)
        self.assertEqual(timeline.cycle_ms, 3_000)

    def test_play_once_has_no_rest(self) -> None:
        """Without a loop there is nothing to wait for."""
        timeline = build_timeline(recording(), loop=False, loop_delay_ms=2_000)
        self.assertEqual(timeline.cycle_ms, 1_000)

    def test_empty_session_cannot_divide_by_zero(self) -> None:
        """A session with no length still produces usable percentages."""
        timeline = build_timeline(
            recording(duration_ms=0, lines=()), loop=False, loop_delay_ms=0
        )
        self.assertEqual(timeline.cycle_ms, 1)
        self.assertEqual(timeline.percent(0), "0.0000")


class BucketTest(PtyReelTestCase):
    """Times are quantised, so nearby events share one rule."""

    def test_same_bucket_shares_a_class(self) -> None:
        """Two events a few milliseconds apart animate together."""
        timeline = build_timeline(
            recording(lines=(line(0, "ab", start_ms=500, step_ms=1),)),
            loop=True,
            loop_delay_ms=0,
        )
        self.assertEqual(timeline.reveal_class(500), timeline.reveal_class(501))
        self.assertEqual(len(timeline.reveals), 1)

    def test_different_buckets_do_not_share(self) -> None:
        """Events a bucket apart animate separately."""
        timeline = build_timeline(
            recording(lines=(line(0, "ab", start_ms=500, step_ms=BUCKET_MS),)),
            loop=True,
            loop_delay_ms=0,
        )
        self.assertEqual(len(timeline.reveals), 2)

    def test_first_bucket_needs_no_animation(self) -> None:
        """Something present from the first frame is simply drawn."""
        timeline = build_timeline(
            recording(lines=(line(0, "ab", start_ms=0),)), loop=True, loop_delay_ms=0
        )
        self.assertEqual(timeline.reveal_class(0), "")
        self.assertEqual(timeline.reveals, ())

    def test_names_follow_time(self) -> None:
        """Class names are numbered in the order things appear."""
        timeline = build_timeline(
            recording(lines=(line(0, "abc", start_ms=100, step_ms=200),)),
            loop=True,
            loop_delay_ms=0,
        )
        self.assertEqual([name for name, _ in timeline.reveals], ["r0", "r1", "r2"])
        self.assertEqual(timeline.reveal_class(100), "r0")
        self.assertEqual(timeline.reveal_class(500), "r2")


class WindowTest(PtyReelTestCase):
    """A line that lives for part of the session gets its own window."""

    def test_permanent_line_needs_no_window(self) -> None:
        """A line present throughout is simply drawn."""
        timeline = build_timeline(recording(), loop=True, loop_delay_ms=0)
        self.assertEqual(timeline.window_class(0, NEVER), "")

    def test_replaced_line_gets_a_window(self) -> None:
        """A line that is replaced needs somewhere to stop."""
        timeline = build_timeline(
            recording(
                lines=(
                    line(0, "a", start_ms=0, death_ms=400),
                    line(0, "b", start_ms=400, birth_ms=400),
                )
            ),
            loop=True,
            loop_delay_ms=0,
        )
        self.assertEqual(len(timeline.windows), 2)
        self.assertNotEqual(timeline.window_class(0, 400), "")
        self.assertNotEqual(timeline.window_class(400, NEVER), "")


class PercentTest(PtyReelTestCase):
    """Percentages are formatted one way, so output stays byte stable."""

    def test_format(self) -> None:
        """Four decimal places, always."""
        timeline = build_timeline(recording(), loop=False, loop_delay_ms=0)
        self.assertEqual(timeline.percent(0), "0.0000")
        self.assertEqual(timeline.percent(500), "50.0000")
        self.assertEqual(timeline.percent(1_000), "100.0000")

    def test_thirds_do_not_wobble(self) -> None:
        """A repeating fraction rounds the same way every time."""
        timeline = build_timeline(
            recording(duration_ms=3_000), loop=False, loop_delay_ms=0
        )
        self.assertEqual(timeline.percent(1_000), "33.3333")


class LimitTest(PtyReelTestCase):
    """A session too long to animate is refused rather than truncated."""

    def test_animation_cap(self) -> None:
        """The cap counts reveals and windows together."""
        count = MAX_ANIMATIONS + 5
        with self.assertRaises(RenderError) as caught:
            build_timeline(
                recording(
                    duration_ms=count * BUCKET_MS,
                    lines=tuple(
                        line(index, "x", start_ms=index * BUCKET_MS)
                        for index in range(1, count + 1)
                    ),
                ),
                loop=True,
                loop_delay_ms=0,
            )
        self.assertIn(str(MAX_ANIMATIONS), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
