"""Colour palettes for the rendered window.

A theme carries colour and nothing else. Every value is validated on
construction, because these strings are written straight into the SVG and a
theme is the only structured colour input the renderer has. Font choice and
geometry live in :mod:`ptyreel.layout`, so a new palette cannot change the
shape of the window.

The sixteen entry ``ansi`` tuple holds the eight normal colours followed by
the eight bright ones, in the order black, red, green, yellow, blue, magenta,
cyan, white.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["THEMES", "Theme", "resolve_theme"]

_COLOUR_RE: Final[re.Pattern[str]] = re.compile(r"\A#[0-9a-f]{6}\Z")
_NAME_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9-]{1,32}\Z")


@dataclass(frozen=True, slots=True, kw_only=True)
class Theme:
    """A validated set of colours for one rendered window.

    Attributes
    ----------
    name : str
        Lower case identifier used in a tape's ``Set Theme`` directive.
    background : str
        Fill of the terminal body.
    surface : str
        Fill of the title bar.
    border : str
        Stroke around the window.
    foreground : str
        Default text colour.
    dim : str
        Text colour for the faint attribute and for the window title.
    ansi : tuple of str
        Sixteen colours: eight normal, then eight bright.
    cursor : str
        Fill of the cursor block.
    traffic_lights : tuple of str
        Three window control colours, left to right.
    backdrop_from : str
        First stop of the gradient behind the window.
    backdrop_to : str
        Second stop of the gradient behind the window.
    shadow : str
        Colour the drop shadow is flooded with.

    Raises
    ------
    ValueError
        If the name or any colour is malformed, or if a tuple is the wrong
        length. Malformed input cannot reach the SVG.
    """

    name: str
    background: str
    surface: str
    border: str
    foreground: str
    dim: str
    ansi: tuple[str, ...]
    cursor: str
    traffic_lights: tuple[str, ...]
    backdrop_from: str
    backdrop_to: str
    shadow: str

    def __post_init__(self) -> None:
        """Reject any value that must not be written into the document."""
        if not _NAME_RE.match(self.name):
            raise ValueError(f"theme name must match {_NAME_RE.pattern}: {self.name!r}")
        if len(self.ansi) != 16:
            raise ValueError(f"ansi needs 16 colours, got {len(self.ansi)}")
        if len(self.traffic_lights) != 3:
            raise ValueError(f"traffic_lights needs 3 colours, got {len(self.traffic_lights)}")
        singles = (
            self.background,
            self.surface,
            self.border,
            self.foreground,
            self.dim,
            self.cursor,
            self.backdrop_from,
            self.backdrop_to,
            self.shadow,
        )
        for colour in (*singles, *self.ansi, *self.traffic_lights):
            if not _COLOUR_RE.match(colour):
                raise ValueError(f"colour must match {_COLOUR_RE.pattern}: {colour!r}")


_GITHUB_DARK: Final[Theme] = Theme(
    name="github-dark",
    background="#0d1117",
    surface="#161b22",
    border="#30363d",
    foreground="#e6edf3",
    dim="#8b949e",
    ansi=(
        "#484f58",
        "#ff7b72",
        "#3fb950",
        "#d29922",
        "#58a6ff",
        "#bc8cff",
        "#39c5cf",
        "#b1bac4",
        "#6e7681",
        "#ffa198",
        "#56d364",
        "#e3b341",
        "#79c0ff",
        "#d2a8ff",
        "#56d4dd",
        "#ffffff",
    ),
    cursor="#58a6ff",
    traffic_lights=("#ff5f56", "#ffbd2e", "#27c93f"),
    backdrop_from="#a8b8cc",
    backdrop_to="#5b6c80",
    shadow="#010409",
)

_GITHUB_LIGHT: Final[Theme] = Theme(
    name="github-light",
    background="#ffffff",
    surface="#f6f8fa",
    border="#d0d7de",
    foreground="#1f2328",
    dim="#656d76",
    ansi=(
        "#24292f",
        "#cf222e",
        "#116329",
        "#4d2d00",
        "#0969da",
        "#8250df",
        "#1b7c83",
        "#6e7781",
        "#57606a",
        "#a40e26",
        "#1a7f37",
        "#633c01",
        "#218bff",
        "#a475f9",
        "#3192aa",
        "#8c959f",
    ),
    cursor="#0969da",
    traffic_lights=("#ff5f56", "#ffbd2e", "#27c93f"),
    backdrop_from="#8c9aad",
    backdrop_to="#c9d1d9",
    shadow="#1f2328",
)

THEMES: Final[dict[str, Theme]] = {
    _GITHUB_DARK.name: _GITHUB_DARK,
    _GITHUB_LIGHT.name: _GITHUB_LIGHT,
}


def resolve_theme(name: str) -> Theme:
    """Look up a theme by name.

    Parameters
    ----------
    name : str
        Theme identifier as written in a tape.

    Returns
    -------
    Theme
        The matching palette.

    Raises
    ------
    KeyError
        If no theme has that name. The message lists the available names so
        a caller can turn it into a tape error without knowing the registry.
    """
    try:
        return THEMES[name]
    except KeyError:
        available = ", ".join(sorted(THEMES))
        raise KeyError(f"unknown theme {name!r}, available: {available}") from None
