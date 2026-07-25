"""Codepoint filtering and XML escaping for everything written into the SVG.

Escaping alone is not enough. XML 1.0 has no representation for most C0
control characters: they are illegal as literal bytes and illegal as numeric
character references, so a document containing one fails to parse no matter
how it was written. Terminal output is full of them. Every string that leaves
this package therefore passes through a filter first and an escape table
second, and there is no code path that escapes without filtering.

Three dispositions apply to a codepoint.

Deleted
    Illegal in XML 1.0, or legal but meaningless in a terminal cell. The C0
    controls other than tab, newline and carriage return, DEL, the C1 block,
    the surrogate range, and every noncharacter.
Replaced
    Legal, but able to change how the surrounding text reads without being
    visible. The bidirectional overrides, the zero width space family and the
    byte order mark become U+FFFD, so tampering shows up instead of silently
    reordering a rendered line.
Escaped
    The five characters XML gives syntactic meaning, plus the three
    whitespace characters an attribute value normalizes away.

Ranges are written out as literal codepoints rather than derived from
:mod:`unicodedata`, so rendered output stays byte stable when CPython updates
its Unicode tables.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "REPLACEMENT",
    "attrs",
    "escape_attr",
    "escape_text",
    "is_storable",
    "sanitize",
]

REPLACEMENT: Final[str] = "�"

_DELETED: Final[frozenset[int]] = frozenset(
    list(range(0x00, 0x09))
    + [0x0B, 0x0C]
    + list(range(0x0E, 0x20))
    + [0x7F]
    + list(range(0x80, 0xA0))
    + list(range(0xD800, 0xE000))
    + list(range(0xFDD0, 0xFDF0))
    + [plane * 0x10000 + offset for plane in range(0x11) for offset in (0xFFFE, 0xFFFF)]
)

_REPLACED: Final[frozenset[int]] = frozenset(
    [0x061C, 0xFEFF]
    + list(range(0x200B, 0x2010))
    + list(range(0x202A, 0x202F))
    + list(range(0x2060, 0x2065))
    + list(range(0x2066, 0x206A))
)

_FILTER_TABLE: Final[dict[int, str | None]] = {
    **{code: None for code in _DELETED},
    **{code: REPLACEMENT for code in _REPLACED},
}

_TEXT_TABLE: Final[dict[int, str | None]] = {
    **_FILTER_TABLE,
    ord("&"): "&amp;",
    ord("<"): "&lt;",
    ord(">"): "&gt;",
}

_ATTR_TABLE: Final[dict[int, str | None]] = {
    **_TEXT_TABLE,
    ord('"'): "&#34;",
    ord("'"): "&#39;",
    0x09: "&#9;",
    0x0A: "&#10;",
    0x0D: "&#13;",
}


def sanitize(text: str) -> str:
    """Remove or replace every codepoint that must not reach an XML document.

    Parameters
    ----------
    text : str
        Arbitrary text, including decoded terminal output.

    Returns
    -------
    str
        The same text with deleted codepoints dropped and replaced
        codepoints turned into U+FFFD. Tab, newline and carriage return
        survive, because they are legal in XML and callers handle them.

    Examples
    --------
    >>> sanitize("a\\x01b")
    'ab'
    >>> sanitize("a\\u202eb") == "a\\ufffdb"
    True
    """
    return text.translate(_FILTER_TABLE)


def escape_text(text: str) -> str:
    """Filter text and escape it for use in an element's text node.

    Only ``&``, ``<`` and ``>`` are escaped. Quotes carry no meaning in a text
    node. Escaping ``>`` is not required on its own, but it makes the
    sequence ``]]>`` unformable, which removes one way to end a section the
    generator never opens.

    Parameters
    ----------
    text : str
        Arbitrary text.

    Returns
    -------
    str
        Text safe to place between an element's start and end tags.

    Examples
    --------
    >>> escape_text('a < b & "c"')
    'a &lt; b &amp; "c"'
    """
    return text.translate(_TEXT_TABLE)


def escape_attr(value: str) -> str:
    """Filter a value and escape it for use inside a double quoted attribute.

    Tab, newline and carriage return are escaped as numeric references
    because an XML parser rewrites each of them to a space during attribute
    value normalization, which would otherwise change the value on the way
    back out.

    Parameters
    ----------
    value : str
        Arbitrary text.

    Returns
    -------
    str
        Text safe to place between the quotes of an attribute value.

    Examples
    --------
    >>> escape_attr('a "b" <c>')
    'a &#34;b&#34; &lt;c&gt;'
    """
    return value.translate(_ATTR_TABLE)


def attrs(**values: str | int | float) -> str:
    """Build an attribute list, escaping every value.

    Underscores in a keyword become hyphens, so ``stroke_width`` produces
    ``stroke-width``. A trailing underscore is stripped, which is how
    ``class_`` reaches the output as ``class``.

    Parameters
    ----------
    **values : str or int or float
        Attribute names and values. Floats are formatted with three decimal
        places so output stays byte stable across platforms.

    Returns
    -------
    str
        A leading space followed by space separated ``name="value"`` pairs,
        or the empty string when no values were given.

    Examples
    --------
    >>> attrs(x=1, class_="cell", fill="#fff")
    ' x="1" class="cell" fill="#fff"'
    """
    parts: list[str] = []
    for name, value in values.items():
        attribute = name.rstrip("_").replace("_", "-")
        text = f"{value:.3f}" if isinstance(value, float) else str(value)
        parts.append(f'{attribute}="{escape_attr(text)}"')
    return "".join(f" {part}" for part in parts)


def is_storable(char: str) -> bool:
    """Report whether a character may be stored in a terminal cell.

    The screen model uses this so filtering happens before a character is
    ever recorded, leaving :func:`sanitize` as a second line of defence
    rather than the only one.

    Parameters
    ----------
    char : str
        A single character.

    Returns
    -------
    bool
        ``False`` for anything deleted or replaced by the filter, and for
        every character below U+0020.
    """
    code = ord(char)
    return code >= 0x20 and code not in _DELETED and code not in _REPLACED
