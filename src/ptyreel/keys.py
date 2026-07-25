"""Key names and the byte sequences a terminal expects for them."""

from __future__ import annotations

from typing import Final

__all__ = ["KEY_MAP", "ctrl_code"]

KEY_MAP: Final[dict[str, str]] = {
    "ENTER": "\r",
    "TAB": "\t",
    "BACKSPACE": "\x7f",
    "ESCAPE": "\x1b",
    "SPACE": " ",
    "UP": "\x1b[A",
    "DOWN": "\x1b[B",
    "RIGHT": "\x1b[C",
    "LEFT": "\x1b[D",
    "HOME": "\x1b[H",
    "END": "\x1b[F",
    "PAGEUP": "\x1b[5~",
    "PAGEDOWN": "\x1b[6~",
    "DELETE": "\x1b[3~",
}


def ctrl_code(letter: str) -> str:
    """Return the control character produced by holding Control and a letter.

    Parameters
    ----------
    letter : str
        A single ASCII letter. Case does not matter.

    Returns
    -------
    str
        The matching character in the range U+0001 to U+001A.

    Raises
    ------
    ValueError
        If the argument is not exactly one ASCII letter.

    Examples
    --------
    >>> ctrl_code("c") == "\\x03"
    True
    >>> ctrl_code("L") == "\\x0c"
    True
    """
    if len(letter) != 1 or not letter.isascii() or not letter.isalpha():
        raise ValueError(f"expected one ASCII letter, got {letter!r}")
    return chr(ord(letter.upper()) - ord("A") + 1)
