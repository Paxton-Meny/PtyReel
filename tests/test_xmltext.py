"""Tests for codepoint filtering and XML escaping.

These are the tests that stop a control character from reaching a document.
XML has no representation for most of them, so one survivor makes the whole
file unparseable, and no amount of escaping fixes it.
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ElementTree

from support import PtyReelTestCase

from ptyreel.xmltext import (
    REPLACEMENT,
    attrs,
    escape_attr,
    escape_text,
    is_storable,
    sanitize,
)

_BOUNDARIES = (
    (0x00, "delete"),
    (0x08, "delete"),
    (0x09, "keep"),
    (0x0A, "keep"),
    (0x0B, "delete"),
    (0x0C, "delete"),
    (0x0D, "keep"),
    (0x0E, "delete"),
    (0x1F, "delete"),
    (0x20, "keep"),
    (0x7E, "keep"),
    (0x7F, "delete"),
    (0x80, "delete"),
    (0x9F, "delete"),
    (0xA0, "keep"),
    (0x061C, "replace"),
    (0x200B, "replace"),
    (0x200F, "replace"),
    (0x2010, "keep"),
    (0x202A, "replace"),
    (0x202E, "replace"),
    (0x202F, "keep"),
    (0xD7FF, "keep"),
    (0xE000, "keep"),
    (0xFDCF, "keep"),
    (0xFDD0, "delete"),
    (0xFDEF, "delete"),
    (0xFDF0, "keep"),
    (0xFEFF, "replace"),
    (0xFFFD, "keep"),
    (0xFFFE, "delete"),
    (0xFFFF, "delete"),
    (0x10000, "keep"),
    (0x1FFFE, "delete"),
    (0x10FFFF, "delete"),
)


class SanitizeTest(PtyReelTestCase):
    """Every codepoint has one of three fates, and the boundaries are exact."""

    def test_boundaries(self) -> None:
        """Each range boundary lands on the expected side."""
        for code, fate in _BOUNDARIES:
            char = chr(code)
            with self.subTest(code=hex(code), fate=fate):
                result = sanitize(char)
                if fate == "delete":
                    self.assertEqual(result, "")
                elif fate == "replace":
                    self.assertEqual(result, REPLACEMENT)
                else:
                    self.assertEqual(result, char)

    def test_surrogates_are_removed(self) -> None:
        """A lone surrogate cannot be encoded, so it must not survive."""
        text = sanitize("a\ud800b")
        self.assertEqual(text, "ab")
        text.encode("utf-8")

    def test_storable_agrees_with_the_filter(self) -> None:
        """The screen's guard and the document's filter accept the same set."""
        for code, fate in _BOUNDARIES:
            char = chr(code)
            with self.subTest(code=hex(code)):
                if fate == "keep" and code >= 0x20:
                    self.assertTrue(is_storable(char))
                else:
                    self.assertFalse(is_storable(char))


class EscapeTest(PtyReelTestCase):
    """Escaping covers the syntax characters and nothing else."""

    def test_text_escapes_three_characters(self) -> None:
        """Quotes carry no meaning between tags, so they stay as they are."""
        self.assertEqual(escape_text('a < b & c > d "e"'), 'a &lt; b &amp; c &gt; d "e"')

    def test_text_cannot_form_a_section_terminator(self) -> None:
        """Escaping the closing angle makes the sequence unformable."""
        self.assertNotIn("]]>", escape_text("]]>"))

    def test_attribute_escapes_quotes_and_whitespace(self) -> None:
        """Tab, newline and return survive a parser's normalisation."""
        self.assertEqual(escape_attr('a"b'), "a&#34;b")
        self.assertEqual(escape_attr("a'b"), "a&#39;b")
        self.assertEqual(escape_attr("a\tb\nc\rd"), "a&#9;b&#10;c&#13;d")

    def test_attribute_round_trips_through_a_parser(self) -> None:
        """What goes in as an attribute comes back out unchanged."""
        for value in ('a "b" c', "a\tb", "a\nb", "a&b<c>", "a'b"):
            with self.subTest(value=value):
                document = f'<x a="{escape_attr(value)}"/>'
                self.assertEqual(ElementTree.fromstring(document).get("a"), value)

    def test_text_round_trips_through_a_parser(self) -> None:
        """What goes in as text comes back out unchanged."""
        for value in ("a & b", "<tag>", "]]>", 'say "hi"'):
            with self.subTest(value=value):
                document = f"<x>{escape_text(value)}</x>"
                self.assertEqual(ElementTree.fromstring(document).text, value)


class AttrsTest(PtyReelTestCase):
    """Attribute lists are built one way, so escaping cannot be skipped."""

    def test_names_and_values(self) -> None:
        """Underscores become hyphens and a trailing one is dropped."""
        self.assertEqual(
            attrs(x=1, stroke_width=2, class_="a"),
            ' x="1" stroke-width="2" class="a"',
        )

    def test_floats_have_fixed_precision(self) -> None:
        """A fixed format keeps rendered output byte stable."""
        self.assertEqual(attrs(x=1.5), ' x="1.500"')
        self.assertEqual(attrs(x=1 / 3), ' x="0.333"')

    def test_values_are_escaped(self) -> None:
        """A hostile value cannot break out of its quotes."""
        self.assertEqual(attrs(a='"><script>'), ' a="&#34;&gt;&lt;script&gt;"')

    def test_no_values_gives_nothing(self) -> None:
        """An empty call adds no stray space."""
        self.assertEqual(attrs(), "")


if __name__ == "__main__":
    unittest.main()
