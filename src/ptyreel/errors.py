"""Exceptions raised by PtyReel.

Every error the package raises on purpose derives from :class:`PtyReelError`.
Errors that can be traced to a line of tape source carry that location and
render it as a prefix, so a message printed by the command line tool reads the
way a compiler diagnostic reads.
"""

from __future__ import annotations

__all__ = [
    "DriverError",
    "PathSecurityError",
    "PtyReelError",
    "RenderError",
    "TapeError",
]


class PtyReelError(Exception):
    """Base class for every error this package raises on purpose."""


class TapeError(PtyReelError):
    """A tape could not be read, parsed, or validated.

    Parameters
    ----------
    message : str
        What went wrong, phrased so it can follow a location prefix.
    source : str
        Name of the tape the problem was found in, as the user named it.
    line : int or None, optional
        One-based line number. ``None`` for a problem with the file as a
        whole, such as a missing directive or an oversized file.

    Attributes
    ----------
    message : str
        The message without its location prefix.
    source : str
        The tape name.
    line : int or None
        The line number, when the problem has one.

    Examples
    --------
    >>> str(TapeError("unknown directive: Wat", source="demo.tape", line=4))
    'demo.tape:4: unknown directive: Wat'
    >>> str(TapeError("no Output directive", source="demo.tape"))
    'demo.tape: no Output directive'
    """

    def __init__(self, message: str, *, source: str, line: int | None = None) -> None:
        """Build the error and format its location prefix."""
        location = f"{source}:{line}" if line is not None else source
        super().__init__(f"{location}: {message}")
        self.message = message
        self.source = source
        self.line = line


class PathSecurityError(TapeError):
    """A path would resolve outside the workspace or names a forbidden entry.

    Parameters
    ----------
    message : str
        What is wrong with the path.
    source : str
        Name of the tape, or the option the path arrived on.
    line : int or None, optional
        One-based line number, when the path came from tape source.
    path : str
        The offending path, appended to the message.

    Attributes
    ----------
    path : str
        The offending path.
    """

    def __init__(
        self,
        message: str,
        *,
        source: str,
        line: int | None = None,
        path: str,
    ) -> None:
        """Build the error with the offending path appended."""
        super().__init__(f"{message}: {path}", source=source, line=line)
        self.path = path


class DriverError(PtyReelError):
    """The pseudo-terminal session could not be started or completed."""


class RenderError(PtyReelError):
    """The recording is too large to render within the documented limits."""
