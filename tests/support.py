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
import math
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
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff￾￿]"
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
        self.assert_content_stays_in_grid(root)
        return root

    def assert_content_stays_in_grid(self, root: ElementTree.Element) -> None:
        """Check that nothing is drawn outside the terminal's rows, at any moment.

        The layout is derived from the document itself: its size, its font
        size, and the padding its content origin implies. Then, at every stop
        of every session animation, each visible run of text and the cursor
        are placed the way a browser places them, with a CSS transform
        replacing the attribute of the element it animates, and checked
        against the grid.

        A run must sit exactly on a row and inside the columns. One below the
        last row is never acceptable, since that text has not scrolled into
        view yet. One above the first row is history and may stay visible as
        long as the clip hides it. The clip itself must not reach into the
        padding, so the rows are the only place anything can appear.

        Parameters
        ----------
        root : xml.etree.ElementTree.Element
            A parsed document.
        """
        from ptyreel.layout import Layout
        from ptyreel.tape import TapeSettings

        scroll = next((e for e in root.iter() if e.get("id") == "scroll"), None)
        if scroll is None:
            return
        style = root.find(f"{SVG_NS}style")
        css = (style.text or "") if style is not None else ""
        rules = _rules(css)
        session = {
            name: stops
            for name, stops in _keyframes(css).items()
            if stops and stops[-1][0] != 100.0
        }
        parents = {child: parent for parent in root.iter() for child in parent}
        animated = _animations_by_element(root, rules)

        def path_to(element: ElementTree.Element) -> list[ElementTree.Element]:
            """Return an element followed by each of its ancestors."""
            path = [element]
            while path[-1] in parents:
                path.append(parents[path[-1]])
            return path

        font = re.search(r"(?<![\w-])text\{[^}]*font-size:(\d+)px", css)
        window = _clip_rect(root, "window-clip")
        self.assertIsNotNone(font, "no font size for the text")
        self.assertIsNotNone(window, "no window clip")
        origin_x = sum(
            x for e in path_to(scroll) for x, _ in translations(e.get("transform") or "")
        )
        layout = Layout.from_settings(
            TapeSettings(
                width=int(root.get("width") or 0),
                height=int(root.get("height") or 0),
                font_size=int(font.group(1)),
                padding=round(origin_x - window[0]),
            )
        )
        grid_top = layout.content_top
        grid_bottom = grid_top + layout.rows * layout.line_height
        band_top, band_bottom = -math.inf, math.inf
        for element in path_to(scroll):
            reference = re.fullmatch(r"url\(#([\w-]+)\)", element.get("clip-path") or "")
            if reference:
                rect = _clip_rect(root, reference.group(1))
                self.assertIsNotNone(rect, f"clip {reference.group(1)} has no rect")
                band_top = max(band_top, rect[1])
                band_bottom = min(band_bottom, rect[1] + rect[3])
        self.assertGreaterEqual(
            band_top, grid_top, f"the content clip starts {grid_top - band_top}px "
            "above the first row, so it shows the padding"
        )
        self.assertLessEqual(
            band_bottom, grid_bottom, f"the content clip ends {band_bottom - grid_bottom}px "
            "below the last row, so it shows the padding"
        )

        motion: dict[int, tuple[object, object]] = {}

        def behaviour(element: ElementTree.Element) -> tuple[object, object]:
            """Return how an element moves and fades: keyframe stops, or a fixed value."""
            known = motion.get(id(element))
            if known is None:
                moves = fades = None
                for name in animated.get(id(element), []):
                    stops = session.get(name, [])
                    if _last_value(stops, "transform") is not None:
                        moves = stops
                    if _last_value(stops, "opacity") is not None:
                        fades = stops
                static_move = tuple(
                    map(sum, zip((0.0, 0.0), *translations(element.get("transform") or "")))
                )
                static_fade = float(_static_value(rules, element, "opacity") or 1)
                known = (moves or static_move, fades or static_fade)
                motion[id(element)] = known
            return known

        def placed(path: list[ElementTree.Element], moment: float) -> tuple[float, float] | None:
            """Return where a path draws its element at a moment, or ``None`` if hidden."""
            x = y = 0.0
            for element in path:
                moves, fades = behaviour(element)
                opacity = (
                    float(_value_at(fades, "opacity", moment))
                    if isinstance(fades, list)
                    else fades
                )
                if opacity <= 0:
                    return None
                if isinstance(moves, list):
                    steps = translations(_value_at(moves, "transform", moment))
                    step = (sum(a for a, _ in steps), sum(b for _, b in steps))
                else:
                    step = moves
                x += step[0]
                y += step[1]
            return x, y

        runs: list[tuple[str, list[ElementTree.Element], float, float, float]] = []
        for text in scroll.iter(f"{SVG_NS}text"):
            for span in text.iter(f"{SVG_NS}tspan"):
                runs.append((
                    f"run {span.text!r}",
                    path_to(span),
                    float(text.get("y") or 0) - layout.baseline_offset,
                    float(span.get("x") or 0),
                    float(span.get("textLength") or 0),
                ))
        for cursor in scroll.iter():
            if cursor.get("id") == "cursor":
                runs.append((
                    "cursor",
                    path_to(cursor),
                    float(cursor.get("y") or 0) - layout.baseline_offset + layout.cursor_offset,
                    float(cursor.get("x") or 0),
                    float(cursor.get("width") or 0),
                ))
        moments = sorted({0.0} | {p for stops in session.values() for p, _ in stops})
        for moment in moments:
            for label, path, rise, left, width in runs:
                where = placed(path, moment)
                if where is None:
                    continue
                row = (where[1] + rise - grid_top) / layout.line_height
                column = (where[0] + left - layout.content_x) / layout.char_width
                span = width / layout.char_width
                at = f"{label} at {moment:g}%"
                self.assertAlmostEqual(row, round(row), 6, f"{at} sits between rows")
                self.assertAlmostEqual(column, round(column), 6, f"{at} sits between columns")
                self.assertGreaterEqual(column, 0, f"{at} starts left of the first column")
                self.assertLessEqual(
                    column + span, layout.cols, f"{at} runs past the last column"
                )
                self.assertLess(
                    round(row), layout.rows,
                    f"{at} is drawn on row {round(row)}, below the last row "
                    f"{layout.rows - 1}, before anything scrolled it into view",
                )
                box_top = grid_top + round(row) * layout.line_height
                if box_top + layout.line_height > band_top and box_top < band_bottom:
                    self.assertGreaterEqual(
                        round(row), 0,
                        f"{at} is drawn on row {round(row)}, above the first row",
                    )

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


def _value_at(stops: list[tuple[float, str]], name: str, moment: float) -> str:
    """Return the value a step-end animation gives a property at a moment."""
    found = None
    for percent, declarations in stops:
        if percent > moment:
            break
        for declaration in declarations.split(";"):
            prop, _, value = declaration.partition(":")
            if prop.strip() == name:
                found = value.strip()
    if found is None:
        raise AssertionError(f"no {name} at {moment}% in an animation that sets it")
    return found


def _animations_by_element(
    root: ElementTree.Element, rules: list[tuple[str, str]]
) -> dict[int, list[str]]:
    """Map each element, by identity, to the animations rules apply to it."""
    found: dict[int, list[str]] = {}
    for selector, body in rules:
        names = _animation_names(body)
        if not names:
            continue
        for part in selector.split(","):
            for element in _select(root, part):
                found.setdefault(id(element), []).extend(names)
    return found


def _clip_rect(
    root: ElementTree.Element, identifier: str
) -> tuple[float, float, float, float] | None:
    """Return the x, y, width and height of the rect a clip path holds."""
    for clip in root.iter(f"{SVG_NS}clipPath"):
        if clip.get("id") == identifier:
            rect = clip.find(f"{SVG_NS}rect")
            if rect is None:
                return None
            return tuple(float(rect.get(key) or 0) for key in ("x", "y", "width", "height"))
    return None
