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
import subprocess
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


def tracked_files(*pathspec: str) -> list[Path] | None:
    """Return the files git tracks, or ``None`` if it cannot say.

    Tests that make claims about the repository have to ask git which files
    belong to it. Walking the filesystem instead sweeps up whatever a
    contributor happens to have lying around, and a gate that fails on an
    untracked scratch file is a gate people learn to ignore.

    Parameters
    ----------
    *pathspec : str
        Patterns to limit the listing, in git's pathspec syntax. No patterns
        means every tracked file.

    Returns
    -------
    list of pathlib.Path or None
        Absolute paths, or ``None`` when this is not a usable work tree, in
        which case the caller should skip rather than guess.
    """
    try:
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--", *pathspec],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return None
    return [REPO_ROOT / name for name in listing.split("\0") if name]


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
        self.assert_transforms_survive_animation(root)
        self.assert_static_opacity_is_final(root)
        return root

    def assert_static_opacity_is_final(self, root: ElementTree.Element) -> None:
        """Check that every element's static opacity is the frame it ends on.

        An animation with no stop at 100% takes its end value from the static
        style. A document that plays once holds that value when it finishes,
        and a reader who asked for stillness sees nothing else, so the static
        style must already be the finished session. When the reveal rule hid
        every cell statically, a document that played once went blank at the
        end and a still one never showed most of its lines.

        An animation that declares its own 100% stop, such as the cursor's
        blink, sets its own end and is not held to this.

        Parameters
        ----------
        root : xml.etree.ElementTree.Element
            A parsed document.
        """
        style = root.find(f"{SVG_NS}style")
        css = (style.text or "") if style is not None else ""
        keyframes = _keyframes(css)
        rules = _rules(css)
        for selector, body in rules:
            for name in _animation_names(body):
                stops = keyframes.get(name, [])
                if not stops or stops[-1][0] == 100.0:
                    continue
                final = _last_value(stops, "opacity")
                if final is None:
                    continue
                for part in selector.split(","):
                    for element in _select(root, part):
                        static = _static_value(rules, element, "opacity") or "1"
                        label = element.get("id") or element.get("class") or element.tag
                        self.assertEqual(
                            float(static),
                            float(final),
                            f"{label}: static opacity {static} is not the "
                            f"opacity {final} the {name} animation ends on",
                        )

    def assert_transforms_survive_animation(self, root: ElementTree.Element) -> None:
        """Check that no CSS transform animation discards a transform attribute.

        A CSS ``transform`` replaces an element's ``transform`` attribute
        instead of composing with it. Static renderers ignore the animation,
        so a mistake here only shows in a browser. An element a transform
        animation targets may therefore carry only the value the animation
        itself rests on, and whatever positions it must sit on an ancestor
        that no animation touches.

        Parameters
        ----------
        root : xml.etree.ElementTree.Element
            A parsed document.
        """
        style = root.find(f"{SVG_NS}style")
        css = (style.text or "") if style is not None else ""
        keyframes = _keyframes(css)
        animated: dict[int, tuple[ElementTree.Element, list[str]]] = {}
        for selector, body in _rules(css):
            names = _animation_names(body)
            if not names:
                continue
            for part in selector.split(","):
                for element in _select(root, part):
                    entry = animated.setdefault(id(element), (element, []))
                    entry[1].extend(names)
        for element, names in animated.values():
            moving = [name for name in names if _final_translation(keyframes, name)]
            if not moving:
                continue
            label = element.get("id") or element.get("class") or element.tag
            self.assertEqual(len(moving), 1, f"{label}: two transform animations")
            final = _final_translation(keyframes, moving[0])
            attribute = element.get("transform")
            if attribute is not None:
                steps = translations(attribute)
                self.assertEqual(
                    len(steps),
                    1,
                    f"{label}: transform attribute {attribute!r} holds more than the "
                    "animated value, and the animation would discard the rest",
                )
                self.assertEqual(
                    steps[0],
                    final,
                    f"{label}: transform attribute {attribute!r} is not the frame "
                    f"the {moving[0]} animation rests on",
                )

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


_KEYFRAMES = re.compile(r"@keyframes\s+([\w-]+)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}")
_STOP = re.compile(r"([^{}]+)\{([^{}]*)\}")
_RULE = re.compile(r"(?<![\w%])([#.][\w-]+(?:\s*,\s*[#.][\w-]+)*)\s*\{([^{}]*)\}")
_MEDIA = re.compile(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}")
_TRANSLATE = re.compile(r"\s*(translate[XY]?)\(([^)]*)\)\s*")


def _keyframes(css: str) -> dict[str, list[tuple[float, str]]]:
    """Map each keyframes name to its stops, in order of position."""
    found: dict[str, list[tuple[float, str]]] = {}
    for name, body in _KEYFRAMES.findall(css):
        stops: list[tuple[float, str]] = []
        for positions, declarations in _STOP.findall(body):
            for position in positions.split(","):
                position = position.strip()
                percent = {"from": 0.0, "to": 100.0}.get(position)
                if percent is None:
                    percent = float(position.rstrip("%"))
                stops.append((percent, declarations))
        found[name] = sorted(stops, key=lambda stop: stop[0])
    return found


def _rules(css: str) -> list[tuple[str, str]]:
    """Return every unconditional rule whose selector names an id or a class."""
    outside = _MEDIA.sub("", _KEYFRAMES.sub("", css))
    return _RULE.findall(outside)


def _last_value(stops: list[tuple[float, str]], name: str) -> str | None:
    """Return the value the last stop declaring a property gives it."""
    found = None
    for _, declarations in stops:
        for declaration in declarations.split(";"):
            prop, _, value = declaration.partition(":")
            if prop.strip() == name:
                found = value.strip()
    return found


def _static_value(
    rules: list[tuple[str, str]], element: ElementTree.Element, name: str
) -> str | None:
    """Return a property's value from the last rule that selects an element.

    Every selector the renderer writes is a single id or a single class, so
    source order decides between the rules that set the same property.
    """
    found = None
    for selector, body in rules:
        if not any(_matches(element, part) for part in selector.split(",")):
            continue
        for declaration in body.split(";"):
            prop, _, value = declaration.partition(":")
            if prop.strip() == name:
                found = value.strip()
    return found


def _matches(element: ElementTree.Element, selector: str) -> bool:
    """Return whether a single ``#id`` or ``.class`` selector matches an element."""
    selector = selector.strip()
    if selector.startswith("#"):
        return element.get("id") == selector[1:]
    return selector[1:] in (element.get("class") or "").split()


def _animation_names(body: str) -> list[str]:
    """Return the animations a rule body applies."""
    names: list[str] = []
    for declaration in body.split(";"):
        prop, _, value = declaration.partition(":")
        prop = prop.strip()
        if prop == "animation-name":
            names.extend(part.strip() for part in value.split(","))
        elif prop == "animation":
            names.extend(part.split()[0] for part in value.split(",") if part.split())
    return [name for name in names if name not in ("none", "none!important")]


def _select(root: ElementTree.Element, selector: str) -> list[ElementTree.Element]:
    """Return the elements a single ``#id`` or ``.class`` selector matches."""
    return [element for element in root.iter() if _matches(element, selector)]


def translations(transform: str) -> list[tuple[float, float]]:
    """Parse a transform made only of translations into one pair per step."""
    steps: list[tuple[float, float]] = []
    position = 0
    while position < len(transform):
        match = _TRANSLATE.match(transform, position)
        if match is None:
            raise AssertionError(f"not a list of translations: {transform!r}")
        kind, raw = match.groups()
        values = [float(part.strip().removesuffix("px")) for part in raw.split(",")]
        if kind == "translateX":
            steps.append((values[0], 0.0))
        elif kind == "translateY":
            steps.append((0.0, values[0]))
        else:
            steps.append((values[0], values[1] if len(values) > 1 else 0.0))
        position = match.end()
    return steps


def _final_translation(
    keyframes: dict[str, list[tuple[float, str]]], name: str
) -> tuple[float, float] | None:
    """Return where a transform animation rests, or ``None`` if it moves nothing."""
    final = None
    for _, declarations in keyframes.get(name, []):
        for declaration in declarations.split(";"):
            prop, _, value = declaration.partition(":")
            if prop.strip() == "transform":
                steps = translations(value)
                final = (sum(x for x, _ in steps), sum(y for _, y in steps))
    return final
