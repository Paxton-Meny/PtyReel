"""Reading a tape file into a validated :class:`ptyreel.tape.Tape`.

The grammar is line oriented. One directive per line, blank lines ignored, and
``#`` starts a comment unless it sits inside a quoted string. Configuration
comes first: ``Output``, ``Require`` and ``Set`` must all appear before the
first action, which is the rule that lets a tape be checked completely before
anything runs.

Every failure raises :class:`ptyreel.errors.TapeError` naming the file and the
line. Parsing is the only place a tape is checked, so the driver and the
renderer can trust what they are handed: a key name is in the key table, a
duration is inside its bounds, typed text holds no control characters, and the
output path is already known to stay inside the workspace.
"""

from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path
from typing import Final

from ptyreel.errors import TapeError
from ptyreel.keys import KEY_MAP
from ptyreel.paths import open_parent, read_text_at, validate_relative_path
from ptyreel.tape import (
    MAX_INSTRUCTIONS,
    MAX_SCHEDULED_MS,
    MAX_TAPE_BYTES,
    MAX_TYPE_CHARS,
    SETTING_SPECS,
    Instruction,
    PressCtrl,
    PressKey,
    SetHidden,
    SleepFor,
    Tape,
    TapeSettings,
    TypeText,
)
from ptyreel.theme import THEMES

__all__ = ["load_tape", "parse_tape"]

_DURATION_RE: Final[re.Pattern[str]] = re.compile(r"\A(\d+(?:\.\d+)?)(ms|s)\Z")
_CTRL_RE: Final[re.Pattern[str]] = re.compile(r"\ACtrl\+([A-Za-z])\Z")
_REQUIRE_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
_ESCAPES: Final[dict[str, str]] = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
}
_BOOLEANS: Final[dict[str, bool]] = {"true": True, "false": False}


def parse_tape(text: str, *, source: str) -> Tape:
    """Parse tape source into a validated tape.

    Parameters
    ----------
    text : str
        The complete tape source.
    source : str
        Name to use in error messages, normally the file name.

    Returns
    -------
    Tape
        A tape whose every field has already been checked.

    Raises
    ------
    TapeError
        On any syntax or validation problem, naming the file and the line.

    Examples
    --------
    >>> tape = parse_tape('Output out/a.svg\\nType "hi"\\nEnter\\n', source="a.tape")
    >>> tape.output
    'out/a.svg'
    >>> len(tape.instructions)
    2
    """
    state = _Parser(source=source)
    for number, raw in enumerate(text.lstrip("﻿").splitlines(), start=1):
        state.line(number, raw)
    return state.finish()


def load_tape(workspace: str | os.PathLike[str], relative: str) -> Tape:
    """Read a tape from inside the workspace and parse it.

    The path is validated as a string first, then read through a descriptor
    walk on POSIX so a symbolic link cannot redirect the read. On other
    platforms, which are development only, the validated components are
    joined and read directly; the string validation already rules out
    traversal, so the two paths accept exactly the same set of files.

    Parameters
    ----------
    workspace : str or path-like
        Directory the tape must live inside.
    relative : str
        Workspace-relative path to the tape.

    Returns
    -------
    Tape
        The parsed tape, with :attr:`ptyreel.tape.Tape.source` set to the
        relative path.

    Raises
    ------
    PathSecurityError
        If the path escapes the workspace or names a forbidden entry.
    TapeError
        If the file is missing, too large, not valid UTF-8, or malformed.
    """
    components = validate_relative_path(relative, source=relative, suffix=".tape")
    root = os.fspath(workspace)
    try:
        if os.name == "posix":
            parent, name = open_parent(root, components, source=relative)
            try:
                text = read_text_at(parent, name, limit=MAX_TAPE_BYTES)
            finally:
                os.close(parent)
        else:
            target = Path(root, *components)
            if target.stat().st_size > MAX_TAPE_BYTES:
                raise ValueError(f"file is larger than {MAX_TAPE_BYTES} bytes")
            text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise TapeError("tape not found", source=relative) from None
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise TapeError(str(exc), source=relative) from None
    return parse_tape(text, source=relative)


class _Parser:
    """Line by line state for one tape."""

    def __init__(self, *, source: str) -> None:
        """Start an empty parse for a named tape."""
        self.source = source
        self.output: str | None = None
        self.output_line = 0
        self.requires: list[tuple[str, int]] = []
        self.collected: dict[str, object] = {}
        self.instructions: list[Instruction] = []
        self.hidden_at: int | None = None
        self.seen_action = False

    def fail(self, message: str, line: int | None) -> TapeError:
        """Build an error naming this tape and a line."""
        return TapeError(message, source=self.source, line=line)

    def line(self, number: int, raw: str) -> None:
        """Consume one source line."""
        body = _strip_comment(raw).strip()
        if not body:
            return
        head, _, rest = body.partition(" ")
        rest = rest.strip()
        if head in ("Output", "Require", "Set"):
            if self.seen_action:
                raise self.fail(f"{head} must come before the first action", number)
            getattr(self, f"_directive_{head.lower()}")(number, rest)
            return
        self.seen_action = True
        if len(self.instructions) >= MAX_INSTRUCTIONS:
            raise self.fail(f"more than {MAX_INSTRUCTIONS} instructions", number)
        self._action(number, head, rest)

    def _directive_output(self, number: int, rest: str) -> None:
        """Record the single Output directive."""
        if self.output is not None:
            raise self.fail("Output is already set", number)
        if not rest:
            raise self.fail("Output needs a path", number)
        path = _unquote(rest, self, number) if rest.startswith('"') else rest
        validate_relative_path(path, source=self.source, line=number, suffix=".svg")
        self.output = path
        self.output_line = number

    def _directive_require(self, number: int, rest: str) -> None:
        """Record a command that must exist before the session runs."""
        if not _REQUIRE_RE.match(rest):
            raise self.fail(f"Require needs a command name, got {rest!r}", number)
        self.requires.append((rest, number))

    def _directive_set(self, number: int, rest: str) -> None:
        """Record one setting, checked against its specification."""
        name, _, value = rest.partition(" ")
        value = value.strip()
        spec = SETTING_SPECS.get(name)
        if spec is None:
            available = ", ".join(sorted(SETTING_SPECS))
            raise self.fail(f"unknown setting {name!r}, available: {available}", number)
        if spec.field in self.collected:
            raise self.fail(f"{name} is already set", number)
        if not value:
            raise self.fail(f"Set {name} needs a value", number)
        self.collected[spec.field] = self._setting_value(number, name, spec, value)

    def _setting_value(self, number: int, name: str, spec: object, value: str) -> object:
        """Read one setting value according to its kind."""
        kind = getattr(spec, "kind")
        if kind == "int":
            if not value.isdigit():
                raise self.fail(f"Set {name} needs a whole number, got {value!r}", number)
            return self._bounded(number, name, int(value), spec)
        if kind == "duration":
            return self._bounded(number, name, self._duration(number, name, value), spec)
        if kind == "bool":
            if value not in _BOOLEANS:
                raise self.fail(f"Set {name} needs true or false, got {value!r}", number)
            return _BOOLEANS[value]
        if kind == "text":
            text = _unquote(value, self, number)
            limit = getattr(spec, "max_length")
            if limit is not None and len(text) > limit:
                raise self.fail(f"Set {name} is longer than {limit} characters", number)
            return " ".join(text.split())
        if kind == "choice":
            text = _unquote(value, self, number)
            choices = getattr(spec, "choices") or ()
            if text not in choices:
                allowed = ", ".join(choices)
                raise self.fail(f"Set {name} must be one of: {allowed}", number)
            return text
        text = _unquote(value, self, number)
        if text not in THEMES:
            available = ", ".join(sorted(THEMES))
            raise self.fail(f"unknown theme {text!r}, available: {available}", number)
        return text

    def _bounded(self, number: int, name: str, value: int, spec: object) -> int:
        """Check a numeric setting against its range."""
        low = getattr(spec, "minimum")
        high = getattr(spec, "maximum")
        if low is not None and value < low:
            raise self.fail(f"Set {name} must be at least {low}, got {value}", number)
        if high is not None and value > high:
            raise self.fail(f"Set {name} must be at most {high}, got {value}", number)
        return value

    def _duration(self, number: int, what: str, value: str) -> int:
        """Read a duration literal in milliseconds."""
        match = _DURATION_RE.match(value)
        if match is None:
            raise self.fail(
                f"{what} needs a duration such as 250ms or 2s, got {value!r}", number
            )
        amount = float(match.group(1))
        return round(amount * (1 if match.group(2) == "ms" else 1_000))

    def _action(self, number: int, head: str, rest: str) -> None:
        """Record one action instruction."""
        if head == "Type":
            if not rest:
                raise self.fail("Type needs a quoted string", number)
            text = _unquote(rest, self, number)
            if len(text) > MAX_TYPE_CHARS:
                raise self.fail(f"Type is longer than {MAX_TYPE_CHARS} characters", number)
            self.instructions.append(TypeText(number, text))
            return
        if head == "Sleep":
            self.instructions.append(
                SleepFor(number, self._bounded_sleep(number, self._duration(number, "Sleep", rest)))
            )
            return
        if head in ("Hide", "Show"):
            self._visibility(number, head, rest)
            return
        control = _CTRL_RE.match(head)
        if control is not None:
            self._no_argument(number, head, rest)
            self.instructions.append(PressCtrl(number, control.group(1).lower()))
            return
        key = head.upper()
        if key in KEY_MAP:
            self._no_argument(number, head, rest)
            self.instructions.append(PressKey(number, key))
            return
        raise self.fail(f"unknown directive: {head}", number)

    def _bounded_sleep(self, number: int, duration_ms: int) -> int:
        """Check a sleep against its range."""
        if not 1 <= duration_ms <= 30_000:
            raise self.fail(f"Sleep must be between 1ms and 30s, got {duration_ms}ms", number)
        return duration_ms

    def _no_argument(self, number: int, head: str, rest: str) -> None:
        """Reject an argument on a directive that takes none."""
        if rest:
            raise self.fail(f"{head} takes no argument, got {rest!r}", number)

    def _visibility(self, number: int, head: str, rest: str) -> None:
        """Record a Hide or Show, checking that they pair up."""
        self._no_argument(number, head, rest)
        if head == "Hide":
            if self.hidden_at is not None:
                raise self.fail(f"already hidden since line {self.hidden_at}", number)
            self.hidden_at = number
            self.instructions.append(SetHidden(number, True))
            return
        if self.hidden_at is None:
            raise self.fail("Show without a matching Hide", number)
        self.hidden_at = None
        self.instructions.append(SetHidden(number, False))

    def finish(self) -> Tape:
        """Check whole-file rules and build the tape."""
        if self.output is None:
            raise self.fail("no Output directive", None)
        if self.hidden_at is not None:
            raise self.fail(f"Hide on line {self.hidden_at} was never followed by Show", None)
        settings = dataclasses.replace(TapeSettings(), **self.collected)
        tape = Tape(
            source=self.source,
            output=self.output,
            output_line=self.output_line,
            requires=tuple(self.requires),
            settings=settings,
            instructions=tuple(self.instructions),
        )
        scheduled = tape.scheduled_ms()
        if scheduled > MAX_SCHEDULED_MS:
            raise self.fail(
                f"declared timing adds up to {scheduled}ms, "
                f"the limit is {MAX_SCHEDULED_MS}ms",
                None,
            )
        return tape


def _strip_comment(raw: str) -> str:
    """Remove a trailing comment, respecting quoted strings."""
    quoted = False
    escaped = False
    for index, char in enumerate(raw):
        if escaped:
            escaped = False
        elif char == "\\" and quoted:
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char == "#" and not quoted:
            return raw[:index]
    return raw


def _unquote(value: str, state: _Parser, number: int) -> str:
    """Read a double quoted string, resolving its escapes."""
    if len(value) < 2 or not value.startswith('"'):
        raise state.fail(f"expected a quoted string, got {value!r}", number)
    out: list[str] = []
    index = 1
    while index < len(value):
        char = value[index]
        if char == '"':
            if index != len(value) - 1:
                raise state.fail("unexpected text after the closing quote", number)
            return "".join(out)
        if char == "\\":
            index += 1
            if index >= len(value):
                break
            replacement = _ESCAPES.get(value[index])
            if replacement is None:
                raise state.fail(f"unknown escape: \\{value[index]}", number)
            out.append(replacement)
            index += 1
            continue
        if char < " " or char == "\x7f":
            raise state.fail("control character in a quoted string", number)
        out.append(char)
        index += 1
    raise state.fail("unterminated quoted string", number)
