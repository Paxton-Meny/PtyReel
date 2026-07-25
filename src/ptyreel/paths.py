"""Keeping every file this tool touches inside the workspace.

Containment is done in two stages, and the split matters. The first stage is
pure string validation with no filesystem access: it runs on any platform, it
is cheap enough to run before anything else, and it rejects the whole class of
paths that should never be considered. The second stage walks the workspace one
directory at a time with an open file descriptor for each step, refusing to
follow a symbolic link. Resolving a path and then opening it by name would
leave a window in which the resolved path stops being the path that gets
written, so the walk keeps a descriptor and every later operation is relative
to it.

The component rule is stricter than it looks. Requiring the first character of
every component to be a letter, a digit or an underscore rejects ``.``, ``..``
and every dotted name in one test, which is what keeps output out of ``.git``
and ``.github`` without maintaining a list of special directories.
"""

from __future__ import annotations

import errno
import os
import re
import secrets
import stat
from typing import Final

from ptyreel.errors import PathSecurityError

__all__ = [
    "MAX_PATH_BYTES",
    "MAX_PATH_COMPONENTS",
    "MAX_SVG_BYTES",
    "open_parent",
    "read_text_at",
    "validate_relative_path",
    "write_atomic",
]

MAX_PATH_BYTES: Final[int] = 1_024
MAX_PATH_COMPONENTS: Final[int] = 16
MAX_SVG_BYTES: Final[int] = 4_194_304

_COMPONENT_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9._-]{0,254}\Z")
_DRIVE_RE: Final[re.Pattern[str]] = re.compile(r"\A[A-Za-z]:")


def validate_relative_path(
    raw: str,
    *,
    source: str,
    line: int | None = None,
    suffix: str,
) -> tuple[str, ...]:
    """Check a path string and split it into components.

    No filesystem access happens here, so this runs the same way on every
    platform and can be called before anything else is opened.

    Parameters
    ----------
    raw : str
        The path exactly as the user wrote it.
    source : str
        Name to report the problem against.
    line : int or None, optional
        Line the path came from, when it came from tape source.
    suffix : str
        Required file extension, including the dot.

    Returns
    -------
    tuple of str
        The path components, guaranteed to contain only characters from
        ``A-Za-z0-9._-``.

    Raises
    ------
    PathSecurityError
        If the path is absolute, names a drive, contains a backslash, a null
        byte, a control character, an empty component, a dotted component,
        too many components, an over-long component, or the wrong suffix.

    Examples
    --------
    >>> validate_relative_path("docs/demo.svg", source="t.tape", suffix=".svg")
    ('docs', 'demo.svg')
    """

    def fail(message: str) -> PathSecurityError:
        """Build a rejection naming this path."""
        return PathSecurityError(message, source=source, line=line, path=raw)

    if not raw:
        raise fail("path is empty")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise fail(f"path is longer than {MAX_PATH_BYTES} bytes")
    if "\x00" in raw:
        raise fail("path contains a null byte")
    if any(char < " " or char == "\x7f" for char in raw):
        raise fail("path contains a control character")
    if "\\" in raw:
        raise fail("path contains a backslash")
    if raw.startswith("/"):
        raise fail("path is absolute")
    if _DRIVE_RE.match(raw):
        raise fail("path names a drive")
    if raw.startswith("~"):
        raise fail("path starts with a home directory reference")
    components = raw.split("/")
    if any(component == "" for component in components):
        raise fail("path has an empty component")
    if len(components) > MAX_PATH_COMPONENTS:
        raise fail(f"path has more than {MAX_PATH_COMPONENTS} components")
    for component in components:
        if not _COMPONENT_RE.match(component):
            raise fail(f"path component is not allowed: {component}")
    last = components[-1]
    if not last.endswith(suffix) or len(last) <= len(suffix):
        raise fail(f"path must name a {suffix} file")
    return tuple(components)


def open_parent(
    workspace: str,
    components: tuple[str, ...],
    *,
    source: str,
    line: int | None = None,
    create: bool = False,
) -> tuple[int, str]:
    """Walk into the workspace and return a descriptor for the parent.

    Each step opens the next directory relative to the descriptor for the
    previous one, refusing to follow a symbolic link. The workspace root
    itself is resolved normally, because a runner may legitimately place the
    workspace behind a link and the root is the trust anchor rather than
    something being checked.

    Parameters
    ----------
    workspace : str
        Directory every path must stay inside.
    components : tuple of str
        Output of :func:`validate_relative_path`.
    source : str
        Name to report a problem against.
    line : int or None, optional
        Line the path came from.
    create : bool, optional
        Whether missing intermediate directories are created.

    Returns
    -------
    tuple
        An open directory descriptor and the final component's name. The
        caller owns the descriptor and must close it.

    Raises
    ------
    PathSecurityError
        If any intermediate component is a symbolic link, is not a
        directory, or is missing when ``create`` is false.
    NotImplementedError
        On a platform without directory descriptors.
    """
    if os.name != "posix":
        raise NotImplementedError("writing output requires a POSIX platform")

    def fail(message: str, path: str) -> PathSecurityError:
        """Build a rejection naming a partial path."""
        return PathSecurityError(message, source=source, line=line, path=path)

    root = os.path.realpath(workspace)
    if not os.path.isdir(root):
        raise fail("workspace is not a directory", workspace)
    current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        for depth, component in enumerate(components[:-1]):
            partial = "/".join(components[: depth + 1])
            try:
                nxt = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise fail("directory does not exist", partial) from None
                os.mkdir(component, 0o755, dir_fd=current)
                nxt = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise fail(
                        "path component is a symbolic link or not a directory", partial
                    ) from None
                raise
            os.close(current)
            current = nxt
    except BaseException:
        os.close(current)
        raise
    return current, components[-1]


def read_text_at(parent_fd: int, name: str, *, limit: int) -> str:
    """Read a regular file through a pinned parent descriptor.

    Parameters
    ----------
    parent_fd : int
        Descriptor returned by :func:`open_parent`.
    name : str
        Final path component.
    limit : int
        Largest number of bytes accepted.

    Returns
    -------
    str
        The decoded contents.

    Raises
    ------
    OSError
        If the entry is missing, is a symbolic link, or is not a regular
        file.
    ValueError
        If the file is larger than ``limit`` or is not valid UTF-8.
    """
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode):
            raise OSError(errno.EINVAL, "not a regular file", name)
        if info.st_size > limit:
            raise ValueError(f"file is larger than {limit} bytes: {name}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(handle, 65_536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError(f"file is larger than {limit} bytes: {name}")
            chunks.append(chunk)
    finally:
        os.close(handle)
    return b"".join(chunks).decode("utf-8")


def write_atomic(parent_fd: int, name: str, text: str) -> None:
    """Write a file so readers never see a partial document.

    The content goes to a uniquely named temporary file in the destination
    directory, is flushed to disk, and is then renamed over the destination.
    Both operations happen through the pinned parent descriptor, so a
    directory swapped in after the walk cannot redirect the write.

    Parameters
    ----------
    parent_fd : int
        Descriptor returned by :func:`open_parent`.
    name : str
        Final path component.
    text : str
        Document to write.

    Raises
    ------
    ValueError
        If the encoded document is larger than :data:`MAX_SVG_BYTES`.
    NotImplementedError
        On a platform without directory descriptors.
    """
    if os.name != "posix":
        raise NotImplementedError("writing output requires a POSIX platform")
    data = text.encode("utf-8")
    if len(data) > MAX_SVG_BYTES:
        raise ValueError(f"rendered document is larger than {MAX_SVG_BYTES} bytes")
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    handle = os.open(temporary, flags, 0o644, dir_fd=parent_fd)
    try:
        written = 0
        while written < len(data):
            written += os.write(handle, data[written:])
        os.fsync(handle)
    finally:
        os.close(handle)
    try:
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        raise
    os.fsync(parent_fd)
