"""Turning recorded times into CSS animation names and percentages.

Two kinds of event need animating. A cell appears once and stays. A line
version appears and may later be replaced. Both are expressed as an opacity
switch on a shared cycle, so every animated element in the document runs one
animation of the same duration and they stay in step for ever. Giving each
element its own delay instead would look right on the first pass and drift
apart on the second, because a delay shifts an element's phase rather than
its position in a shared cycle.

Times are quantised into buckets before they become names. Everything written
during the same bucket shares one class and one keyframes rule, so the size of
the stylesheet follows how many distinct moments the session has, not how many
characters it printed.

The switch itself is one keyframe. With ``step-end`` timing the value of a
property holds until the next keyframe is reached, so ``0%{opacity:0}
40%{opacity:1}`` keeps a cell hidden for the first forty percent of the cycle
and shows it for the rest, using two stops rather than four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ptyreel.errors import RenderError
from ptyreel.recording import NEVER, Recording

__all__ = ["BUCKET_MS", "MAX_ANIMATIONS", "Timeline", "build_timeline"]

BUCKET_MS: Final[int] = 40
MAX_ANIMATIONS: Final[int] = 4_000


@dataclass(frozen=True, slots=True, kw_only=True)
class Timeline:
    """Names and percentages for one document's animations.

    Attributes
    ----------
    cycle_ms : int
        Length of one full pass, including the rest before a replay.
    duration_ms : int
        Length of the session itself, without the rest.
    loop : bool
        Whether the animation repeats.
    reveals : tuple
        Pairs of class name and bucket, ordered by time. One per moment
        anything appeared.
    windows : tuple
        Triples of class name, birth bucket and death bucket, ordered by
        time. A death bucket of :data:`ptyreel.recording.NEVER` means the
        line survives to the end.
    """

    cycle_ms: int
    duration_ms: int
    loop: bool
    reveals: tuple[tuple[str, int], ...]
    windows: tuple[tuple[str, int, int], ...]
    _reveal_names: dict[int, str]
    _window_names: dict[tuple[int, int], str]

    def percent(self, time_ms: int) -> str:
        """Return a time as a percentage of the cycle.

        Parameters
        ----------
        time_ms : int
            A time inside the cycle.

        Returns
        -------
        str
            The percentage with four decimal places, so output stays byte
            stable and two nearby buckets never collapse onto one stop.
        """
        return f"{100.0 * time_ms / self.cycle_ms:.4f}"

    def reveal_class(self, time_ms: int) -> str:
        """Return the class that makes something appear at a time.

        Parameters
        ----------
        time_ms : int
            When the thing should appear.

        Returns
        -------
        str
            A class name, or the empty string for something visible from
            the first frame.
        """
        return self._reveal_names.get(time_ms // BUCKET_MS, "")

    def window_class(self, birth_ms: int, death_ms: int) -> str:
        """Return the class that shows a line for part of the cycle.

        Parameters
        ----------
        birth_ms : int
            When the line version appears.
        death_ms : int
            When it is replaced, or :data:`ptyreel.recording.NEVER`.

        Returns
        -------
        str
            A class name, or the empty string for a line that is present
            for the whole cycle.
        """
        death = NEVER if death_ms == NEVER else death_ms // BUCKET_MS
        return self._window_names.get((birth_ms // BUCKET_MS, death), "")


def build_timeline(
    recording: Recording, *, loop: bool, loop_delay_ms: int
) -> Timeline:
    """Collect every distinct moment in a recording and name it.

    Parameters
    ----------
    recording : Recording
        The captured session.
    loop : bool
        Whether the animation should repeat.
    loop_delay_ms : int
        How long the finished session rests before repeating. Ignored when
        ``loop`` is false.

    Returns
    -------
    Timeline
        Ordered names and the cycle length.

    Raises
    ------
    RenderError
        If the session needs more than :data:`MAX_ANIMATIONS` distinct
        animations, which means it is far longer than this tool is meant to
        record.
    """
    cycle_ms = max(1, recording.duration_ms + (loop_delay_ms if loop else 0))

    reveal_buckets: set[int] = set()
    window_keys: set[tuple[int, int]] = set()
    for version in recording.lines:
        for stamp in version.times:
            if stamp != NEVER:
                reveal_buckets.add(stamp // BUCKET_MS)
        death = NEVER if version.death_ms == NEVER else version.death_ms // BUCKET_MS
        birth = version.birth_ms // BUCKET_MS
        if birth or death != NEVER:
            window_keys.add((birth, death))
    reveal_buckets.discard(0)

    total = len(reveal_buckets) + len(window_keys)
    if total > MAX_ANIMATIONS:
        raise RenderError(
            f"session needs {total} animations, the limit is {MAX_ANIMATIONS}"
        )

    ordered_reveals = sorted(reveal_buckets)
    reveal_names = {bucket: f"r{index}" for index, bucket in enumerate(ordered_reveals)}
    ordered_windows = sorted(window_keys, key=lambda key: (key[0], key[1]))
    window_names = {key: f"w{index}" for index, key in enumerate(ordered_windows)}
    return Timeline(
        cycle_ms=cycle_ms,
        duration_ms=recording.duration_ms,
        loop=loop,
        reveals=tuple((reveal_names[bucket], bucket) for bucket in ordered_reveals),
        windows=tuple((window_names[key], key[0], key[1]) for key in ordered_windows),
        _reveal_names=reveal_names,
        _window_names=window_names,
    )
