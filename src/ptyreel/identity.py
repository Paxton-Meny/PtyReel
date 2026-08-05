"""Recording a session as a generic machine rather than as yours.

A rendered SVG is made to be published. Whatever the session printed goes into
it verbatim, so a demo that runs ``whoami`` commits your account name to a
repository, and one that prints a path commits your home directory. Warning
about that after the fact puts the work on the person recording. Removing the
identity before it is ever recorded does not.

Two layers are needed, because the environment only reaches half of it. A
shell reads ``$USER`` and ``$HOME`` from the environment, so pinning those is
enough for ``echo $USER`` and for ``~``. ``whoami``, ``id`` and ``hostname``
ask the kernel and the account database instead, and no environment variable
changes what they answer. Those are caught by substituting the real values out
of the output stream.

The session also gets a fresh home directory of its own. Pinning ``HOME`` to a
name that does not exist would break anything that writes there, so it points
somewhere real and temporary, and that path is substituted for the preset on
the way out. A tape therefore cannot leave anything behind in your real home,
which is worth having on its own.
"""

from __future__ import annotations

import getpass
import os
import socket
from collections.abc import Mapping
from typing import Final

from ptyreel.rewrite import Rule, literal_rule, word_rule

__all__ = ["IDENTITY_PRESETS", "identity_environ", "identity_rules"]

IDENTITY_PRESETS: Final[dict[str, str]] = {
    "user": "LocalUser",
    "home": "/home/LocalUser",
    "host": "localhost",
}

_MIN_SUBSTITUTABLE: Final[int] = 3


def identity_environ(session_home: str) -> dict[str, str]:
    """Return the environment entries that describe a generic machine.

    Parameters
    ----------
    session_home : str
        A real, writable directory to use as the session's home.

    Returns
    -------
    dict
        Values for the variables a shell reads to answer questions about who
        and where it is.
    """
    return {
        "HOME": session_home,
        "USER": IDENTITY_PRESETS["user"],
        "LOGNAME": IDENTITY_PRESETS["user"],
        "HOSTNAME": IDENTITY_PRESETS["host"],
    }


def identity_rules(
    *, session_home: str, environ: Mapping[str, str] | None = None
) -> list[Rule]:
    """Build the substitutions that remove this machine from the output.

    Order matters. Paths are replaced before bare names, so a home directory
    becomes the preset home rather than a preset user name with the rest of
    the path left dangling.

    A bare user name or host name is only replaced where it stands alone.
    Both are short and ordinary enough to appear inside unrelated words: an
    account called ``runner`` must not turn ``runner.py`` into something else.
    Names shorter than three characters are left alone entirely, because at
    that length the risk of rewriting unrelated text outweighs the gain.

    Parameters
    ----------
    session_home : str
        The real directory being used as the session's home.
    environ : mapping or None, optional
        Environment to read the real home from. Defaults to the current one.

    Returns
    -------
    list of Rule
        Substitutions to apply to the output stream, longest first.
    """
    source = os.environ if environ is None else environ
    preset_home = IDENTITY_PRESETS["home"]
    rules: list[Rule] = []

    paths = {session_home, os.path.realpath(session_home)}
    real_home = source.get("HOME")
    if real_home:
        paths.update({real_home, os.path.realpath(real_home)})
    for path in sorted(paths, key=len, reverse=True):
        if path and path != "/":
            rules.append(literal_rule(path, preset_home))

    candidates = [(_real_user(source), IDENTITY_PRESETS["user"])]
    candidates.extend((form, IDENTITY_PRESETS["host"]) for form in _host_forms())
    for name, preset in candidates:
        if name and len(name) >= _MIN_SUBSTITUTABLE and name != preset:
            rules.append(word_rule(name, preset))
    return rules


def _real_user(environ: Mapping[str, str]) -> str:
    """Return this machine's account name, or the empty string."""
    for variable in ("USER", "LOGNAME"):
        value = environ.get(variable)
        if value:
            return value
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return ""


def _host_forms() -> tuple[str, ...]:
    """Return this machine's host name in the forms it prints as.

    macOS answers ``hostname`` with the full form, ``name.local``, while the
    short form appears in prompts and logs. The short form's rule refuses to
    match where a dot follows, which is right for a file name and wrong for
    the full host name, so the full form gets a rule of its own. Longest
    first, so it wins where both could apply.
    """
    try:
        full = socket.gethostname()
    except OSError:
        return ()
    short = full.split(".")[0]
    return tuple(sorted({full, short}, key=len, reverse=True))
