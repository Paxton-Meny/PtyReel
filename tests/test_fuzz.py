"""Property tests over generated terminal output.

The corpus is built from a seeded generator, so a failure is reproducible.
Every case reports the payload as a pasteable line, and the fix is to add that
line to the regression table rather than to change the seed.

The highest value property here is chunking invariance. The driver hands the
screen whatever a read returned, which can split a sequence, a character or a
secret anywhere. Feeding the same bytes in one piece and in many must produce
the same screen, and that single assertion covers the whole escape parser.
"""

from __future__ import annotations

import base64
import random
import unittest
import xml.etree.ElementTree as ElementTree
from typing import Final

from support import XML_FORBIDDEN, PtyReelTestCase, dump

from fixtures import BASE

from ptyreel.recording import NEVER
from ptyreel.screen import TerminalScreen
from ptyreel.svg import render_svg

ESCAPE_SNIPPETS: Final[tuple[str, ...]] = (
    "\x1b[0m",
    "\x1b[1;31m",
    "\x1b[38;5;196m",
    "\x1b[38;2;1;2;3m",
    "\x1b[48;5;21m",
    "\x1b[38:5:9m",
    "\x1b[2J",
    "\x1b[K",
    "\x1b[1K",
    "\x1b[2K",
    "\x1b[2;3H",
    "\x1b[H",
    "\x1b[3A",
    "\x1b[4C",
    "\x1b[9d",
    "\x1b[5G",
    "\x1b[?2004h",
    "\x1b[?2004l",
    "\x1b[6n",
    "\x1b]0;a title\x07",
    "\x1b]2;other\x1b\\",
    "\x1b(B",
    "\x1bM",
    "\x1b[",
    "\x1b[3",
    "\x1b]0;unterminated",
    "\x1b",
)
SEEDS: Final[tuple[int, ...]] = tuple(range(1_000, 1_040))
PAYLOAD_LENGTH: Final[int] = 512
REGRESSIONS: Final[tuple[tuple[str, str], ...]] = ()


def payload(seed: int, length: int) -> str:
    """Build a deterministic pseudo-terminal stream.

    Parameters
    ----------
    seed : int
        Chooses the stream. The same seed always gives the same bytes.
    length : int
        Roughly how many characters to produce.

    Returns
    -------
    str
        A mixture of printable text, control characters and real escape
        sequences, including deliberately truncated ones.
    """
    rng = random.Random(seed)
    out: list[str] = []
    while len(out) < length:
        roll = rng.random()
        if roll < 0.55:
            out.append(chr(32 + int(rng.random() * 95)))
        elif roll < 0.72:
            out.append("\n\r\t\b\x07"[int(rng.random() * 5)])
        elif roll < 0.80:
            out.append(chr(0x00A0 + int(rng.random() * 0x2000)))
        else:
            out.extend(ESCAPE_SNIPPETS[int(rng.random() * len(ESCAPE_SNIPPETS))])
    return "".join(out[:length])


def chunks(text: str, seed: int) -> list[str]:
    """Split text into pieces the way a sequence of reads would."""
    rng = random.Random(seed ^ 0x5EED)
    pieces: list[str] = []
    position = 0
    while position < len(text):
        size = 1 + int(rng.random() * 64)
        pieces.append(text[position : position + size])
        position += size
    return pieces


class ScreenPropertyTest(PtyReelTestCase):
    """Properties that must hold for any input at all."""

    def cases(self) -> list[tuple[str, str]]:
        """Return the generated corpus followed by any pinned regressions."""
        generated = [(f"seed-{seed}", payload(seed, PAYLOAD_LENGTH)) for seed in SEEDS]
        pinned = [
            (name, base64.b64decode(blob).decode("utf-8"))
            for name, blob in REGRESSIONS
        ]
        return generated + pinned

    def fuzz_failure(self, text: str, detail: str) -> None:
        """Fail with a line that can be pasted into the regression table."""
        blob = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self.fail(f'{detail}\npin this as a regression row:\n    ("case", "{blob}"),')

    def test_feeding_in_pieces_is_the_same_as_all_at_once(self) -> None:
        """A read boundary must not change what ends up on screen."""
        for name, text in self.cases():
            with self.subTest(case=name):
                whole = TerminalScreen(cols=40, rows=8)
                whole.feed(text, time_ms=0)
                split = TerminalScreen(cols=40, rows=8)
                for piece in chunks(text, hash(name) & 0xFFFF):
                    split.feed(piece, time_ms=0)
                if dump(whole.snapshot()) != dump(split.snapshot()):
                    self.fuzz_failure(text, "chunking changed the screen")

    def test_never_raises_and_stays_in_bounds(self) -> None:
        """No input crashes the model or writes outside the grid."""
        for name, text in self.cases():
            with self.subTest(case=name):
                screen = TerminalScreen(cols=40, rows=8)
                try:
                    screen.feed(text, time_ms=0)
                except Exception as exc:
                    self.fuzz_failure(text, f"feed raised {exc!r}")
                recording = screen.snapshot()
                for version in recording.lines:
                    self.assertEqual(len(version.chars), 40)
                for _, cursor_line, cursor_column in recording.cursors:
                    self.assertGreaterEqual(cursor_line, 0)
                    self.assertLess(cursor_column, 40)

    def test_only_storable_characters_are_kept(self) -> None:
        """Nothing that would break a document ever reaches a cell."""
        for name, text in self.cases():
            with self.subTest(case=name):
                screen = TerminalScreen(cols=40, rows=8)
                screen.feed(text, time_ms=0)
                for version in screen.snapshot().lines:
                    if XML_FORBIDDEN.search(version.chars):
                        self.fuzz_failure(text, "a forbidden codepoint was stored")


class RenderPropertyTest(PtyReelTestCase):
    """Anything the screen produces can be rendered and parsed."""

    def test_rendering_always_parses(self) -> None:
        """The renderer never emits a document an XML parser rejects."""
        for seed in SEEDS[:12]:
            with self.subTest(seed=seed):
                screen = TerminalScreen(cols=40, rows=8)
                for step, piece in enumerate(chunks(payload(seed, 256), seed)):
                    screen.feed(piece, time_ms=step * 10)
                recording = screen.snapshot()
                document = render_svg(recording, settings=BASE)
                ElementTree.fromstring(document)
                self.assertIsNone(XML_FORBIDDEN.search(document))

    def test_rendering_is_idempotent(self) -> None:
        """Rendering the same screen twice gives the same bytes."""
        screen = TerminalScreen(cols=40, rows=8)
        screen.feed(payload(1_000, 256), time_ms=0)
        recording = screen.snapshot()
        self.assertEqual(
            render_svg(recording, settings=BASE), render_svg(recording, settings=BASE)
        )

    def test_blank_cells_are_never_drawn(self) -> None:
        """A cell that was never written has no reveal time."""
        screen = TerminalScreen(cols=40, rows=8)
        screen.feed(payload(1_001, 256), time_ms=0)
        for version in screen.snapshot().lines:
            for column, stamp in enumerate(version.times):
                if stamp == NEVER:
                    self.assertEqual(version.chars[column], " ")


if __name__ == "__main__":
    unittest.main()
