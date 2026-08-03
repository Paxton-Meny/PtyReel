"""Redacting secret-looking values before they reach a committed file.

Masking runs twice, and the second pass is the one that matters. The first
pass filters the byte stream as it arrives, which stops a secret from ever
being interpreted as part of an escape sequence and catches a value split
across two reads. The second pass runs over the finished screen, where a value
that the terminal wrapped across a line boundary or rebuilt with a carriage
return is finally contiguous. A stream filter alone cannot see that.

Replacements always keep the original length. A shorter replacement would
shift every following column and desynchronise the recorded screen from the
program that drew it.

What this cannot promise: a value the program transformed before printing, a
value the tape hard-codes rather than reading from the environment, and a
value too short to tell apart from ordinary text. The stronger control is the
child environment allowlist in :mod:`ptyreel.driver`, which means a workflow
token is not present inside a tape session at all.

Because that allowlist is the real control, this pass leans away from guessing.
A wrong guess is not a harmless extra precaution: it silently replaces correct
output with asterisks, and the person recording the session has no way to tell
why. So the name match is deliberately narrow, the standard variables that
collide with it are named and excluded, and a value that reads as a filesystem
path is left alone.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from ptyreel.recording import NEVER, LineVersion, Recording
from ptyreel.rewrite import Rule, literal_rule

__all__ = [
    "MASK_CHAR",
    "MIN_SECRET_LENGTH",
    "collect_secrets",
    "mask_recording",
    "mask_text",
    "secret_forms",
    "secret_rules",
]

MASK_CHAR: Final[str] = "*"
MIN_SECRET_LENGTH: Final[int] = 8

_SECRET_SEGMENTS: Final[frozenset[str]] = frozenset(
    {
        "apikey",
        "auth",
        "bearer",
        "cert",
        "cookie",
        "credential",
        "credentials",
        "key",
        "keys",
        "pass",
        "passphrase",
        "passwd",
        "password",
        "pat",
        "private",
        "pwd",
        "salt",
        "secret",
        "secrets",
        "signature",
        "token",
        "tokens",
    }
)
_NEVER_SECRET: Final[frozenset[str]] = frozenset(
    {
        "GPG_TTY",
        "OLDPWD",
        "PWD",
        "SSH_AGENT_PID",
        "SSH_AUTH_SOCK",
        "XDG_SESSION_TYPE",
    }
)
_UNINTERESTING: Final[frozenset[str]] = frozenset(
    {"", "0", "1", "false", "no", "none", "null", "true", "yes"}
)
_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9]+")


def collect_secrets(
    environ: Mapping[str, str], *, min_length: int = MIN_SECRET_LENGTH
) -> tuple[str, ...]:
    """Pick the environment values that look like secrets.

    A name matches when one of its underscore separated segments is a known
    secret word. Matching by segment rather than by substring keeps
    ``MONKEY_COUNT`` from looking like a key.

    Parameters
    ----------
    environ : mapping
        Environment to inspect.
    min_length : int, optional
        Shortest value considered worth masking.

    Returns
    -------
    tuple of str
        Distinct values, longest first.

    Examples
    --------
    >>> collect_secrets({"MY_API_TOKEN": "s3cr3t-value", "MONKEY_COUNT": "12"})
    ('s3cr3t-value',)
    """
    found: set[str] = set()
    for name, value in environ.items():
        if name in _NEVER_SECRET:
            continue
        segments = {segment.lower() for segment in _SPLIT_RE.split(name) if segment}
        if not segments & _SECRET_SEGMENTS:
            continue
        if len(value) < min_length or value.lower() in _UNINTERESTING:
            continue
        if len(set(value)) == 1:
            continue
        if value.isdigit() and len(value) < 16:
            continue
        if value.startswith("/"):
            continue
        found.add(value)
    return tuple(sorted(found, key=lambda item: (-len(item), item)))


def secret_forms(values: Iterable[str]) -> tuple[str, ...]:
    """Expand secrets into the encodings a shell pipeline can produce.

    Parameters
    ----------
    values : iterable of str
        Raw secret values.

    Returns
    -------
    tuple of str
        Every raw value plus its base64, url-safe base64, percent-encoded,
        JSON-escaped and hexadecimal forms, longest first so the longest
        match wins.
    """
    forms: set[str] = set()
    for value in values:
        raw = value.encode("utf-8")
        padded = base64.b64encode(raw).decode("ascii")
        urlsafe = base64.urlsafe_b64encode(raw).decode("ascii")
        forms.update(
            {
                value,
                padded,
                padded.rstrip("="),
                urlsafe,
                urlsafe.rstrip("="),
                urllib.parse.quote(value, safe=""),
                json.dumps(value)[1:-1],
                raw.hex(),
                raw.hex().upper(),
            }
        )
    kept = {form for form in forms if len(form) >= MIN_SECRET_LENGTH}
    return tuple(sorted(kept, key=lambda item: (-len(item), item)))


def mask_text(value: str, forms: Sequence[str]) -> str:
    """Replace every occurrence of every form, longest first.

    Parameters
    ----------
    value : str
        Text to redact.
    forms : sequence of str
        Output of :func:`secret_forms`.

    Returns
    -------
    str
        The text with each match replaced by mask characters of the same
        length.
    """
    for form in forms:
        if form and form in value:
            value = value.replace(form, MASK_CHAR * len(form))
    return value


def secret_rules(forms: Sequence[str]) -> list[Rule]:
    """Build substitutions that replace each secret with mask characters.

    The replacement is the same length as what it replaces. Length is the one
    thing worth preserving here: a program that prints a value and then moves
    the cursor relative to it would draw in the wrong place otherwise.

    Parameters
    ----------
    forms : sequence of str
        Output of :func:`secret_forms`, longest first.

    Returns
    -------
    list of Rule
        Substitutions for :class:`ptyreel.rewrite.StreamRewriter`.
    """
    return [literal_rule(form, MASK_CHAR * len(form)) for form in forms if form]


def mask_recording(recording: Recording, forms: Sequence[str]) -> Recording:
    """Redact secrets that only become contiguous on the finished screen.

    Each line version is searched on its own, and each pair of neighbouring
    lines whose lifetimes overlap is searched joined together, which is how a
    value broken by a line wrap is caught.

    Parameters
    ----------
    recording : Recording
        The captured session.
    forms : sequence of str
        Output of :func:`secret_forms`.

    Returns
    -------
    Recording
        A recording with matched cells replaced. The original is unchanged.
    """
    if not forms:
        return recording
    cells = [list(version.chars) for version in recording.lines]
    for index, version in enumerate(recording.lines):
        _mask_span(cells[index], "".join(cells[index]), forms, 0)
        for other, neighbour in enumerate(recording.lines):
            if neighbour.line != version.line + 1 or not _overlap(version, neighbour):
                continue
            joined = "".join(cells[index]) + "".join(cells[other])
            _mask_pair(cells[index], cells[other], joined, forms)
    lines = tuple(
        LineVersion(
            line=version.line,
            birth_ms=version.birth_ms,
            death_ms=version.death_ms,
            chars="".join(cells[index]),
            styles=version.styles,
            times=version.times,
        )
        for index, version in enumerate(recording.lines)
    )
    return Recording(
        cols=recording.cols,
        rows=recording.rows,
        duration_ms=recording.duration_ms,
        styles=recording.styles,
        lines=lines,
        scrolls=recording.scrolls,
        cursors=recording.cursors,
    )


def _overlap(first: LineVersion, second: LineVersion) -> bool:
    """Report whether two line versions are ever on screen together."""
    first_end = first.death_ms if first.death_ms != NEVER else None
    second_end = second.death_ms if second.death_ms != NEVER else None
    if first_end is not None and first_end <= second.birth_ms:
        return False
    if second_end is not None and second_end <= first.birth_ms:
        return False
    return True


def _mask_span(cells: list[str], text: str, forms: Sequence[str], offset: int) -> None:
    """Mask matches found in text back onto a single cell list."""
    for form in forms:
        start = text.find(form)
        while start != -1:
            for position in range(start, start + len(form)):
                target = position - offset
                if 0 <= target < len(cells):
                    cells[target] = MASK_CHAR
            start = text.find(form, start + 1)


def _mask_pair(
    first: list[str], second: list[str], joined: str, forms: Sequence[str]
) -> None:
    """Mask matches that straddle the boundary between two lines."""
    split = len(first)
    for form in forms:
        start = joined.find(form)
        while start != -1:
            stop = start + len(form)
            if start < split < stop:
                for position in range(start, stop):
                    if position < split:
                        first[position] = MASK_CHAR
                    else:
                        second[position - split] = MASK_CHAR
            start = joined.find(form, start + 1)
