"""Shared bootstrap and assertions for the test suite.

The gate runs ``python -m unittest discover -s tests``, which puts this
directory on the import path but not ``src``. Importing this module first is
what makes the package importable, so every test module imports it before it
imports anything from ``ptyreel``.

This module does not match the discovery pattern, so it is never collected as
a test.
"""

from __future__ import annotations

import difflib
import os
import re
import sys
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Final

TESTS_ROOT: Final[Path] = Path(__file__).resolve().parent
REPO_ROOT: Final[Path] = TESTS_ROOT.parent
SRC_ROOT: Final[Path] = REPO_ROOT / "src"
GOLDEN_DIR: Final[Path] = TESTS_ROOT / "golden"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

POSIX_ONLY = unittest.skipUnless(os.name == "posix", "needs a POSIX platform")
HAS_BASH = unittest.skipUnless(
    os.path.exists("/bin/bash") or os.path.exists("/usr/bin/bash"), "needs bash"
)

XML_FORBIDDEN: Final[re.Pattern[str]] = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff￾￿]"
)
SVG_NS: Final[str] = "{http://www.w3.org/2000/svg}"
_BANNED_MARKUP: Final[tuple[str, ...]] = (
    "<!DOCTYPE",
    "<!ENTITY",
    "<![CDATA[",
    "<script",
    "<foreignObject",
    "<image",
    "xlink:",
    " href=",
    "@import",
    "<!--",
    "&nbsp;",
)


def dump(recording: object) -> str:
    """Return the final visible text of a recording, one line per row.

    Only the surviving version of each line is used, so the result is what a
    reader sees at the end of the session.

    Parameters
    ----------
    recording : Recording
        A captured or hand-built session.

    Returns
    -------
    str
        Lines joined by newlines, with trailing blanks removed from each.
    """
    from ptyreel.recording import NEVER

    latest: dict[int, str] = {}
    for version in recording.lines:  # type: ignore[attr-defined]
        if version.death_ms == NEVER:
            latest[version.line] = version.chars
    if not latest:
        return ""
    return "\n".join(
        latest.get(index, "").rstrip() for index in range(max(latest) + 1)
    )


class PtyReelTestCase(unittest.TestCase):
    """Base case carrying the assertions several modules need."""

    def assert_golden(self, name: str, actual: str) -> None:
        """Compare rendered output against a stored document.

        Parameters
        ----------
        name : str
            Golden file stem.
        actual : str
            Freshly rendered document.
        """
        path = GOLDEN_DIR / f"{name}.svg"
        if not path.exists():
            self.fail(
                f"golden {name}.svg does not exist, "
                "create it with: python tests/regenerate_golden.py"
            )
        expected = path.read_bytes().decode("utf-8")
        self.assertNotIn("\r", actual, "rendered output must not contain a return")
        if expected == actual:
            return
        diff = list(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile=f"golden/{name}.svg",
                tofile="rendered",
                n=2,
                lineterm="",
            )
        )
        head = "\n".join(diff[:40])
        extra = "" if len(diff) <= 40 else f"\n... {len(diff) - 40} further diff lines"
        self.fail(
            f"golden mismatch for {name}\n{head}{extra}\n"
            "regenerate with: python tests/regenerate_golden.py"
        )

    def assert_svg_sane(self, svg: str) -> ElementTree.Element:
        """Check the structural rules every rendered document must meet.

        Parameters
        ----------
        svg : str
            A rendered document.

        Returns
        -------
        xml.etree.ElementTree.Element
            The parsed root, so a caller can assert further.
        """
        root = ElementTree.fromstring(svg)
        self.assertEqual(root.tag, f"{SVG_NS}svg")
        self.assertEqual(root.get("role"), "img")
        self.assertIsNone(XML_FORBIDDEN.search(svg), "forbidden codepoint in output")
        self.assertNotIn("\r", svg)
        svg.encode("utf-8")
        for banned in _BANNED_MARKUP:
            self.assertNotIn(banned, svg, f"{banned} must never appear")
        identifiers = set()
        for element in root.iter():
            local = element.tag.rsplit("}", 1)[-1]
            self.assertNotIn(
                local, {"script", "foreignObject", "image", "handler"}, "banned element"
            )
            for name in element.keys():
                self.assertFalse(name.startswith("on"), f"event attribute {name}")
                self.assertNotIn("href", name, f"reference attribute {name}")
            found = element.get("id")
            if found is not None:
                self.assertNotIn(found, identifiers, f"duplicate id {found}")
                self.assertRegex(found, r"\A[a-z][a-z0-9-]*\Z")
                identifiers.add(found)
        for value in _attribute_values(root):
            for reference in re.findall(r"url\(#([^)]+)\)", value):
                self.assertIn(reference, identifiers, f"dangling reference {reference}")
            self.assertNotRegex(value, r"\A(https?:|//|data:|javascript:)")
        self.assert_css_closed(svg, root)
        return root

    def assert_css_closed(self, svg: str, root: ElementTree.Element) -> None:
        """Check that every class and animation is both defined and used."""
        style = root.find(f"{SVG_NS}style")
        self.assertIsNotNone(style)
        css = style.text or ""
        defined = set(re.findall(r"\.([A-Za-z][\w-]*)\s*(?=[,{])", css))
        used: set[str] = set()
        for element in root.iter():
            value = element.get("class")
            if value:
                used.update(value.split())
        self.assertEqual(used - defined, set(), "class used but never defined")
        self.assertEqual(defined - used, set(), "class defined but never used")
        keyframes = set(re.findall(r"@keyframes\s+([\w-]+)", css))
        named = set(re.findall(r"animation-name:([\w-]+)", css))
        for shorthand in re.findall(r"animation:([^;}]+)", css):
            for part in shorthand.split(","):
                head = part.split()[0]
                if head != "none!important":
                    named.add(head)
        self.assertEqual(named - keyframes, set(), "animation without keyframes")
        self.assertEqual(keyframes - named, set(), "keyframes never used")


def _attribute_values(root: ElementTree.Element) -> list[str]:
    """Collect every attribute value in a document."""
    return [value for element in root.iter() for value in element.attrib.values()]
