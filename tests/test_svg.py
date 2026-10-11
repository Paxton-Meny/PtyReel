"""Tests for the renderer.

Golden files pin the exact bytes. The structural assertions catch the classes
of mistake a golden cannot: a document that no longer parses, a class that is
used but never defined, an animation without keyframes, a reference to an
element that is not there.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ElementTree

from support import SRC_ROOT, SVG_NS, PtyReelTestCase, translations

from fixtures import BASE, COLS, RECORDINGS, SETTINGS, line

from ptyreel.errors import RenderError
from ptyreel.layout import Layout
from ptyreel.recording import NEVER, Recording, Style
from ptyreel.svg import render_svg
from ptyreel.timeline import MAX_ANIMATIONS

_DIGEST_SNIPPET = """
import hashlib, json, sys
from ptyreel.recording import Recording
from ptyreel.tape import TapeSettings
from ptyreel.svg import render_svg
data = json.load(sys.stdin)
svg = render_svg(Recording.from_dict(data["recording"]), settings=TapeSettings(**data["settings"]))
print(hashlib.sha256(svg.encode("utf-8")).hexdigest())
"""


class GoldenTest(PtyReelTestCase):
    """Every fixture renders to the document stored beside it."""

    def test_goldens(self) -> None:
        """A byte for byte comparison, with a readable diff on failure."""
        for name in sorted(RECORDINGS):
            with self.subTest(golden=name):
                document = render_svg(RECORDINGS[name], settings=SETTINGS[name])
                self.assert_golden(name, document)

    def test_goldens_are_sane(self) -> None:
        """Each stored document also passes every structural rule."""
        for name in sorted(RECORDINGS):
            with self.subTest(golden=name):
                document = render_svg(RECORDINGS[name], settings=SETTINGS[name])
                self.assert_svg_sane(document)


class StructureTest(PtyReelTestCase):
    """The document is shaped the way the embedding contexts need."""

    def render(self, name: str = "minimal") -> str:
        """Render one fixture."""
        return render_svg(RECORDINGS[name], settings=SETTINGS[name])

    def test_document_ends_in_one_newline(self) -> None:
        """A trailing newline keeps the file well behaved in a diff."""
        document = self.render()
        self.assertTrue(document.endswith("\n"))
        self.assertFalse(document.endswith("\n\n"))

    def test_title_is_the_first_child(self) -> None:
        """A reader announces the title, so it comes first."""
        root = ElementTree.fromstring(self.render())
        self.assertEqual(list(root)[0].tag, f"{SVG_NS}title")

    def test_size_matches_the_settings(self) -> None:
        """The image is the size the tape asked for."""
        root = ElementTree.fromstring(self.render())
        self.assertEqual(root.get("width"), str(BASE.width))
        self.assertEqual(root.get("height"), str(BASE.height))
        self.assertEqual(root.get("viewBox"), f"0 0 {BASE.width} {BASE.height}")

    def test_text_survives_a_round_trip(self) -> None:
        """What was on screen is what the document says, character for character."""
        root = ElementTree.fromstring(self.render("escaping"))
        texts = [
            "".join(span.text or "" for span in element)
            for element in root.iter(f"{SVG_NS}text")
        ]
        self.assertIn("a < b & c > d", [text.rstrip() for text in texts])
        self.assertIn('"q" \'p\' ]]>', [text.rstrip() for text in texts])

    def test_hostile_title_is_inert(self) -> None:
        """A title that looks like markup is text, not markup."""
        document = self.render("escaping")
        self.assertNotIn("<script>", document)
        root = ElementTree.fromstring(document)
        title = root.find(f"{SVG_NS}title")
        self.assertIn("alert(1)", title.text or "")

    def test_runs_carry_position_and_width(self) -> None:
        """Columns line up even when the reader has none of the fonts."""
        root = ElementTree.fromstring(self.render())
        spans = list(root.iter(f"{SVG_NS}tspan"))
        self.assertTrue(spans)
        for span in spans:
            self.assertIsNotNone(span.get("x"))
            self.assertIsNotNone(span.get("textLength"))
            self.assertEqual(span.get("lengthAdjust"), "spacingAndGlyphs")

    def test_reduced_motion_block_is_present(self) -> None:
        """A reader who asked for stillness sees the finished session."""
        document = self.render()
        self.assertIn("prefers-reduced-motion:reduce", document)
        self.assertIn("animation:none!important", document)


class AnimationTest(PtyReelTestCase):
    """Looping and playing once are one mechanism with two settings."""

    def test_loop_shares_one_cycle(self) -> None:
        """Every animation runs on the same clock, so they stay in step."""
        document = render_svg(RECORDINGS["buckets"], settings=SETTINGS["buckets"])
        self.assertIn("animation-iteration-count:infinite", document)
        self.assertIn("animation-duration:5.000s", document)

    def test_play_once_holds_the_last_frame(self) -> None:
        """Without a loop the session rests on its final state."""
        document = render_svg(RECORDINGS["once"], settings=SETTINGS["once"])
        self.assertIn("animation-iteration-count:1", document)
        self.assertIn("animation-fill-mode:forwards", document)
        self.assertNotIn("infinite", document.split("#cursor")[0])

    def test_reveal_percentages_increase(self) -> None:
        """Later text appears later, which is the whole point."""
        document = render_svg(RECORDINGS["minimal"], settings=SETTINGS["minimal"])
        stops = [
            float(part)
            for part in _percentages(document)
        ]
        self.assertEqual(stops, sorted(stops))
        self.assertTrue(all(0 <= stop <= 100 for stop in stops))

    def test_dead_line_versions_switch_off(self) -> None:
        """A replaced line disappears rather than showing through."""
        document = render_svg(RECORDINGS["buckets"], settings=SETTINGS["buckets"])
        self.assertRegex(
            document,
            r"@keyframes w\d+\{0%\{opacity:0\}[\d.]+%\{opacity:1\}[\d.]+%\{opacity:0\}\}",
        )

    def test_scrolling_moves_the_content(self) -> None:
        """A session that scrolled slides its content upward."""
        document = render_svg(RECORDINGS["buckets"], settings=SETTINGS["buckets"])
        self.assertIn("@keyframes scroll", document)
        self.assertIn("translateY(-", document)

    def test_no_scrolling_means_no_scroll_animation(self) -> None:
        """A session that fits needs no movement at all."""
        document = render_svg(RECORDINGS["minimal"], settings=SETTINGS["minimal"])
        self.assertNotIn("@keyframes scroll", document)


class ScrollOriginTest(PtyReelTestCase):
    """The scroll animation moves the content without losing its origin.

    A CSS transform replaces the transform attribute of the element it
    animates. When the content origin shared that attribute with the scroll
    offset, every browser drew the text shifted up and left for the whole
    animation, while a static renderer showed the final frame correctly.
    """

    def render(self) -> str:
        """Render the fixture that scrolls."""
        return render_svg(RECORDINGS["buckets"], settings=SETTINGS["buckets"])

    def test_scroll_group_carries_only_the_offset(self) -> None:
        """The animated group holds the scroll offset and nothing else."""
        root = ElementTree.fromstring(self.render())
        group = _by_id(root, "scroll")
        self.assertEqual(group.get("transform"), "translate(0,-24)")

    def test_origin_sits_on_an_unanimated_ancestor(self) -> None:
        """What the animation cannot reach still places the content."""
        layout = Layout.from_settings(SETTINGS["buckets"])
        root = ElementTree.fromstring(self.render())
        parents = {child: parent for parent in root.iter() for child in parent}
        x = y = 0.0
        ancestor = parents.get(_by_id(root, "scroll"))
        while ancestor is not None:
            transform = ancestor.get("transform")
            if transform is not None:
                self.assertIsNone(ancestor.get("id"), "a rule could select it")
                self.assertIsNone(ancestor.get("class"), "a rule could select it")
                for step_x, step_y in translations(transform):
                    x += step_x
                    y += step_y
            ancestor = parents.get(ancestor)
        self.assertEqual((x, y), (layout.content_x, layout.content_top))

    def test_check_rejects_an_origin_on_the_scroll_group(self) -> None:
        """The structural rule catches the layout that was broken."""
        layout = Layout.from_settings(SETTINGS["buckets"])
        origin = f"translate({layout.content_x},{layout.content_top})"
        document = self.render().replace(
            f'<g transform="{origin}">\n<g id="scroll" transform="translate(0,-24)"',
            f'<g>\n<g id="scroll" transform="{origin} translate(0,-24)"',
        )
        self.assertIn(f"{origin} translate(0,-24)", document)
        with self.assertRaisesRegex(AssertionError, "scroll: transform attribute"):
            self.assert_svg_sane(document)

    def test_check_rejects_a_cursor_resting_elsewhere(self) -> None:
        """The cursor's attribute must be the frame its track animation ends on."""
        document = self.render().replace(
            'transform="translate(36,50)"', 'transform="translate(36,26)"'
        )
        self.assertIn('transform="translate(36,26)"', document)
        with self.assertRaisesRegex(AssertionError, "cursor: transform attribute"):
            self.assert_svg_sane(document)

    def test_scrolled_once_rests_on_the_last_frame(self) -> None:
        """Without a loop, the scroll and the cursor hold their final place."""
        settings = dataclasses.replace(SETTINGS["buckets"], loop=False)
        document = render_svg(RECORDINGS["buckets"], settings=settings)
        self.assertIn(
            "#scroll{animation:scroll 4.000s step-end 1;animation-fill-mode:forwards}",
            document,
        )
        self.assert_svg_sane(document)


class DeterminismTest(PtyReelTestCase):
    """The same recording always produces the same bytes."""

    def test_rendering_twice_is_identical(self) -> None:
        """Nothing in the renderer varies between calls."""
        for name in sorted(RECORDINGS):
            with self.subTest(fixture=name):
                first = render_svg(RECORDINGS[name], settings=SETTINGS[name])
                second = render_svg(RECORDINGS[name], settings=SETTINGS[name])
                self.assertEqual(first, second)

    def test_hash_seed_does_not_change_the_output(self) -> None:
        """No unordered collection reaches the output order."""
        import json

        payload = json.dumps(
            {
                "recording": RECORDINGS["buckets"].to_dict(),
                "settings": dataclasses.asdict(SETTINGS["buckets"]),
            }
        )
        expected = hashlib.sha256(
            render_svg(RECORDINGS["buckets"], settings=SETTINGS["buckets"]).encode()
        ).hexdigest()
        for seed in ("0", "1", "random"):
            with self.subTest(seed=seed):
                result = subprocess.run(
                    [sys.executable, "-c", _DIGEST_SNIPPET],
                    input=payload,
                    capture_output=True,
                    text=True,
                    check=True,
                    env={
                        **os.environ,
                        "PYTHONHASHSEED": seed,
                        "PYTHONPATH": str(SRC_ROOT),
                        "PYTHONIOENCODING": "utf-8",
                    },
                )
                self.assertEqual(result.stdout.strip(), expected)


class CodepointTest(PtyReelTestCase):
    """No character on screen can produce a document that fails to parse."""

    def test_every_codepoint_renders(self) -> None:
        """A sweep of the whole basic plane, in blocks."""
        for block in range(0x20, 0x10000, 0x1000):
            with self.subTest(block=hex(block)):
                text = "".join(chr(block + offset) for offset in range(0, 0x1000, 64))
                recording = Recording(
                    cols=len(text),
                    rows=2,
                    duration_ms=100,
                    styles=(Style(),),
                    lines=(line(0, text, start_ms=0, cols=len(text)),),
                    scrolls=((0, 0),),
                    cursors=((0, 0, 0),),
                )
                document = render_svg(recording, settings=BASE)
                ElementTree.fromstring(document)

    def test_control_characters_are_dropped(self) -> None:
        """A control character cannot be escaped, so it must not survive."""
        text = "a\x01b\x1fc\x7fd"
        recording = Recording(
            cols=len(text),
            rows=2,
            duration_ms=100,
            styles=(Style(),),
            lines=(line(0, text, start_ms=0, cols=len(text)),),
            scrolls=((0, 0),),
            cursors=((0, 0, 0),),
        )
        self.assert_svg_sane(render_svg(recording, settings=BASE))


class LimitTest(PtyReelTestCase):
    """The renderer refuses a session it cannot represent."""

    def test_too_many_animations(self) -> None:
        """A session with more distinct moments than the cap is refused."""
        count = MAX_ANIMATIONS + 10
        recording = Recording(
            cols=1,
            rows=2,
            duration_ms=count * 100,
            styles=(Style(),),
            lines=tuple(
                line(index, "x", start_ms=index * 100, cols=1)
                for index in range(count)
            ),
            scrolls=((0, 0),),
            cursors=((0, 0, 0),),
        )
        with self.assertRaises(RenderError):
            render_svg(recording, settings=BASE)


class EmptyTest(PtyReelTestCase):
    """A session that produced nothing still renders a window."""

    def test_empty_recording(self) -> None:
        """No lines, no animations, still a valid document."""
        recording = Recording(
            cols=COLS,
            rows=3,
            duration_ms=0,
            styles=(Style(),),
            lines=(),
            scrolls=((0, 0),),
            cursors=((0, 0, 0),),
        )
        self.assert_svg_sane(render_svg(recording, settings=BASE))

    def test_blank_line_is_not_drawn(self) -> None:
        """A line nothing was written to produces no element."""
        recording = Recording(
            cols=COLS,
            rows=3,
            duration_ms=100,
            styles=(Style(),),
            lines=(
                LineVersionBlank := line(0, "", start_ms=0),
            ),
            scrolls=((0, 0),),
            cursors=((0, 0, 0),),
        )
        self.assertEqual(LineVersionBlank.times, (NEVER,) * COLS)
        root = ElementTree.fromstring(render_svg(recording, settings=BASE))
        self.assertEqual(list(root.iter(f"{SVG_NS}tspan")), [])


def _by_id(root: ElementTree.Element, identifier: str) -> ElementTree.Element:
    """Return the one element carrying an id."""
    found = [element for element in root.iter() if element.get("id") == identifier]
    if len(found) != 1:
        raise AssertionError(f"expected one element with id {identifier}")
    return found[0]


def _percentages(document: str) -> list[str]:
    """Pull the reveal stops out of a rendered stylesheet, in order."""
    import re

    return re.findall(r"@keyframes r\d+\{0%\{opacity:0\}([\d.]+)%", document)


if __name__ == "__main__":
    unittest.main()
