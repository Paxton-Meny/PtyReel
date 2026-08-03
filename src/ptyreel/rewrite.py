"""Replacing text in the output stream as it arrives.

Two features need to substitute text before it reaches the screen: redacting
secrets, and replacing the identity of the machine with fixed stand-ins. They
want different replacements but the same mechanism, so the mechanism lives
here once.

Substituting in the stream rather than on the finished screen is deliberate.
A replacement is often a different length from what it replaces, and the
screen is a grid of fixed cells: rewriting there would shift every column
after the match. Feeding the substituted text through the terminal instead
lets it lay the result out the way it would have laid out the original.

A match can straddle two reads, so the tail of each chunk is held back until
enough text has arrived to decide. The held text is bounded by the longest
match any rule can produce.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["Rule", "StreamRewriter", "literal_rule", "rewrite_text", "word_rule"]

_EDGE: str = r"A-Za-z0-9_.:/@-"


@dataclass(frozen=True, slots=True)
class Rule:
    """One substitution.

    Attributes
    ----------
    pattern : re.Pattern
        What to look for.
    replacement : str
        What to put in its place. Written literally, so a backslash in it
        carries no meaning.
    width : int
        Longest text the pattern can match. The stream rewriter holds back
        this much minus one, so a match split across two reads still lands.
    """

    pattern: re.Pattern[str]
    replacement: str
    width: int


def literal_rule(needle: str, replacement: str) -> Rule:
    """Build a rule matching a needle anywhere it appears.

    Parameters
    ----------
    needle : str
        Exact text to find.
    replacement : str
        Text to put in its place.

    Returns
    -------
    Rule
        A rule matching every occurrence.
    """
    return Rule(re.compile(re.escape(needle)), replacement, len(needle))


def word_rule(needle: str, replacement: str) -> Rule:
    """Build a rule matching a needle only when it stands alone.

    A bare user name is short and ordinary enough to appear inside unrelated
    text. On a runner the account is called ``runner``, and replacing that
    everywhere would rewrite ``runner.py`` too. This rule matches only when
    neither neighbour could make the match part of a longer word, path or
    address.

    Parameters
    ----------
    needle : str
        Exact text to find.
    replacement : str
        Text to put in its place.

    Returns
    -------
    Rule
        A rule matching only standalone occurrences.
    """
    pattern = re.compile(
        rf"(?<![{_EDGE}]){re.escape(needle)}(?![{_EDGE}])"
    )
    return Rule(pattern, replacement, len(needle) + 1)


def rewrite_text(text: str, rules: Sequence[Rule]) -> str:
    """Apply every rule to a complete piece of text.

    Parameters
    ----------
    text : str
        Text to rewrite.
    rules : sequence of Rule
        Applied in order, so the caller decides precedence.

    Returns
    -------
    str
        The rewritten text.
    """
    for rule in rules:
        text = rule.pattern.sub(lambda _, value=rule.replacement: value, text)
    return text


class StreamRewriter:
    """Applies rules to output as it arrives, one chunk at a time.

    Parameters
    ----------
    rules : sequence of Rule
        Substitutions to apply. An empty sequence makes this a pass through.
    """

    __slots__ = ("_hold", "_rules", "_tail")

    def __init__(self, rules: Sequence[Rule]) -> None:
        """Prepare a rewriter and size its held tail."""
        self._rules = tuple(rules)
        self._hold = max((rule.width for rule in self._rules), default=1) - 1
        self._tail = ""

    def feed(self, text: str) -> str:
        """Rewrite a chunk and return the part that is safe to release.

        Parameters
        ----------
        text : str
            Newly decoded output.

        Returns
        -------
        str
            Rewritten text, minus a held tail short enough to still become
            part of a match.
        """
        if not self._rules:
            return text
        combined = rewrite_text(self._tail + text, self._rules)
        if self._hold <= 0 or len(combined) <= self._hold:
            self._tail = combined
            return ""
        cut = len(combined) - self._hold
        self._tail = combined[cut:]
        return combined[:cut]

    def flush(self) -> str:
        """Return whatever is still held back.

        Returns
        -------
        str
            The remaining rewritten text.
        """
        remaining = rewrite_text(self._tail, self._rules) if self._rules else self._tail
        self._tail = ""
        return remaining
