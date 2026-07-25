"""The two operations the command line and the action perform.

Checking and rendering share all of their validation, and the split between
them is the point where a pseudo-terminal would have to open. Everything a
tape can get wrong is caught on the checking side: the grammar, the limits,
the output path, the missing command, the image that is too small for its
font. A check therefore runs anywhere, including on a machine with no
pseudo-terminals at all, and a render that gets past the check is failing for
a reason that belongs to the session rather than to the tape.

The driver is imported inside :func:`render_tape` rather than at the top of
this module, so importing PtyReel never pulls in a POSIX-only module.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping

from ptyreel.errors import TapeError
from ptyreel.layout import Layout
from ptyreel.parse import load_tape
from ptyreel.paths import open_parent, validate_relative_path, write_atomic
from ptyreel.svg import render_svg
from ptyreel.tape import Tape
from ptyreel.theme import resolve_theme

__all__ = ["check_tape", "render_tape"]


def check_tape(
    workspace: str | os.PathLike[str],
    relative: str,
    *,
    output_override: str | None = None,
) -> tuple[Tape, str]:
    """Load a tape and check everything that does not need a terminal.

    Parameters
    ----------
    workspace : str or path-like
        Directory the tape and its output must stay inside.
    relative : str
        Workspace-relative path to the tape.
    output_override : str or None, optional
        Replacement for the tape's own ``Output`` path.

    Returns
    -------
    tuple
        The parsed tape and the output path that will be written.

    Raises
    ------
    TapeError
        If the tape is malformed, requires a command that is not installed,
        names an unknown theme, or asks for an image too small to hold a
        usable grid.
    PathSecurityError
        If the tape or its output would escape the workspace.
    """
    tape = load_tape(workspace, relative)
    output = tape.output
    if output_override is not None:
        validate_relative_path(output_override, source="--output", suffix=".svg")
        output = output_override
    for command, line in tape.requires:
        if shutil.which(command) is None:
            raise TapeError(
                f"required command is not installed: {command}",
                source=tape.source,
                line=line,
            )
    try:
        Layout.from_settings(tape.settings)
    except ValueError as exc:
        raise TapeError(str(exc), source=tape.source, line=None) from None
    resolve_theme(tape.settings.theme)
    return tape, output


def render_tape(
    workspace: str | os.PathLike[str],
    relative: str,
    *,
    output_override: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Check a tape, play it, and write the rendered document.

    Parameters
    ----------
    workspace : str or path-like
        Directory the tape and its output must stay inside.
    relative : str
        Workspace-relative path to the tape.
    output_override : str or None, optional
        Replacement for the tape's own ``Output`` path.
    environ : mapping or None, optional
        Environment used for inherited variables and secret detection.

    Returns
    -------
    str
        The workspace-relative path that was written.

    Raises
    ------
    DriverError
        If the session could not be run to completion.
    RenderError
        If the session is too large to render.
    """
    from ptyreel.driver import run_tape

    tape, output = check_tape(workspace, relative, output_override=output_override)
    layout = Layout.from_settings(tape.settings)
    recording = run_tape(tape, layout=layout, environ=environ)
    document = render_svg(recording, settings=tape.settings)
    components = validate_relative_path(
        output,
        source=tape.source if output_override is None else "--output",
        line=tape.output_line if output_override is None else None,
        suffix=".svg",
    )
    parent, name = open_parent(
        os.fspath(workspace), components, source=tape.source, create=True
    )
    try:
        write_atomic(parent, name, document)
    finally:
        os.close(parent)
    return output
