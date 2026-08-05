"""Running a tape inside a real pseudo-terminal.

This is the only module that needs POSIX, and the only one that is not a pure
function of its arguments. Importing it on a platform without ``pty`` fails
immediately with a message that says so, which is why nothing else in the
package imports it at module level.

The clock the recording uses is not the wall clock. A tape declares how fast
it types and how long it waits, so the animation's timeline can be computed
from the tape rather than measured from the machine. Output is stamped at the
moment the command that produced it was entered. Real time still passes, and
still bounds the session, but it never reaches the recording. Two runs of the
same tape against the same program therefore produce the same bytes, which is
what makes a rendered demo something a repository can hold and check rather
than something that churns on every render.

The child gets a small, fixed environment. A tape session cannot see a
workflow token or any other secret the surrounding job holds, because those
variables are never passed in. That, rather than redaction, is the control
that keeps them out of a committed image.

The session is also recorded as a generic machine rather than as yours. It
runs with a fresh home directory of its own and with the identity presets in
:mod:`ptyreel.identity`, so a tape can neither leave anything in your real
home nor write your account name into an image meant to be published.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import tempfile
import time
from collections.abc import Mapping, Sequence
from typing import Final

from ptyreel.errors import DriverError
from ptyreel.identity import identity_environ, identity_rules
from ptyreel.keys import KEY_MAP, ctrl_code
from ptyreel.layout import Layout
from ptyreel.masking import collect_secrets, mask_recording, secret_forms, secret_rules
from ptyreel.recording import Recording
from ptyreel.rewrite import Rule, StreamRewriter
from ptyreel.screen import TerminalScreen
from ptyreel.tape import (
    BOOT_MS,
    PressCtrl,
    PressKey,
    SetHidden,
    SleepFor,
    Tape,
    TypeText,
)

if os.name != "posix":
    raise ImportError("ptyreel.driver needs a POSIX platform: pty, termios and fcntl")

import codecs
import fcntl
import pty
import struct
import termios

__all__ = ["MAX_PTY_BYTES", "MAX_WALL_MS", "READ_CHUNK", "build_child_env", "run_tape"]

READ_CHUNK: Final[int] = 65_536
MAX_PTY_BYTES: Final[int] = 8_388_608
MAX_WALL_MS: Final[int] = 180_000
_SHELLS: Final[dict[str, tuple[str, ...]]] = {"bash": ("/bin/bash", "/usr/bin/bash")}
_INHERITED: Final[tuple[str, ...]] = ("HOME", "LANG", "LC_ALL", "LOGNAME", "PATH", "TZ", "USER")
_STARTUP_MS: Final[int] = 200
_SETTLE_MS: Final[int] = 100
_GRACE_S: Final[float] = 2.0
_QUIET_S: Final[float] = 0.08
_MAX_SETTLE_S: Final[float] = 3.0
_ECHO_S: Final[float] = 0.5


def build_child_env(
    environ: Mapping[str, str],
    *,
    shell: str,
    cols: int,
    rows: int,
    identity: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the environment the shell runs with.

    Only a short list of variables carries over. Everything else, including
    every secret the surrounding job holds, is dropped.

    Parameters
    ----------
    environ : mapping
        The current environment.
    shell : str
        Absolute path of the shell being run.
    cols, rows : int
        Size of the terminal.
    identity : mapping or None, optional
        Values describing a generic machine, from
        :func:`ptyreel.identity.identity_environ`. Applied last, so they win
        over anything inherited.

    Returns
    -------
    dict
        The child's environment, with a fixed prompt so the recording does
        not depend on the machine it ran on. Apple's bash is told to keep
        quiet too: at interactive startup it prints an advertisement for
        zsh unless ``BASH_SILENCE_DEPRECATION_WARNING`` is set, and that
        banner would open every recording made on macOS. The variable means
        nothing anywhere else.
    """
    child = {name: environ[name] for name in _INHERITED if name in environ}
    child["TERM"] = "xterm-256color"
    child["PS1"] = "$ "
    child["PS2"] = "> "
    child["SHELL"] = shell
    child["COLUMNS"] = str(cols)
    child["LINES"] = str(rows)
    child["HISTFILE"] = "/dev/null"
    child["BASH_SILENCE_DEPRECATION_WARNING"] = "1"
    if identity is not None:
        child.update(identity)
    return child


def resolve_shell(name: str) -> str:
    """Find the executable for a tape's shell setting.

    Parameters
    ----------
    name : str
        A shell name the parser has already checked against its allowlist.

    Returns
    -------
    str
        Absolute path of the executable.

    Raises
    ------
    DriverError
        If no candidate path is executable.
    """
    for candidate in _SHELLS.get(name, ()):
        if os.access(candidate, os.X_OK):
            return candidate
    raise DriverError(f"no executable found for shell {name!r}")


def run_tape(
    tape: Tape, *, layout: Layout, environ: Mapping[str, str] | None = None
) -> Recording:
    """Play a tape in a pseudo-terminal and return what appeared.

    Parameters
    ----------
    tape : Tape
        A parsed, validated tape.
    layout : Layout
        Geometry, which fixes the size of the terminal.
    environ : mapping or None, optional
        Environment to take inherited variables and secrets from. Defaults
        to the current process environment.

    Returns
    -------
    Recording
        The captured session, with secrets redacted when the tape asks for
        it.

    Raises
    ------
    DriverError
        If the shell cannot be started, the session outruns its time or byte
        budget, or the terminal reports an error other than end of file.
    """
    source = os.environ if environ is None else environ
    shell = resolve_shell(tape.settings.shell)
    forms = (
        secret_forms(collect_secrets(source)) if tape.settings.mask_secrets else ()
    )
    with tempfile.TemporaryDirectory(prefix="ptyreel-home-") as session_home:
        rules: list[Rule] = []
        identity: dict[str, str] | None = None
        if tape.settings.anonymize:
            identity = identity_environ(session_home)
            rules.extend(identity_rules(session_home=session_home, environ=source))
        rules.extend(secret_rules(forms))

        session = _Session(tape=tape, layout=layout, rules=rules)
        master, slave = pty.openpty()
        _set_window_size(slave, cols=layout.cols, rows=layout.rows)
        child = os.fork()
        if child == 0:
            _become_shell(master, slave, shell, build_child_env(
                source,
                shell=shell,
                cols=layout.cols,
                rows=layout.rows,
                identity=identity,
            ))
        os.close(slave)
        try:
            recording = session.play(master, child)
        finally:
            _terminate(master, child)
    if forms:
        recording = mask_recording(recording, forms)
    return recording


def _set_window_size(fd: int, *, cols: int, rows: int) -> None:
    """Tell the terminal how many rows and columns it has."""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _become_shell(master: int, slave: int, shell: str, env: dict[str, str]) -> None:
    """Replace this forked child with the shell, or exit without unwinding."""
    try:
        os.close(master)
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        for target in (0, 1, 2):
            os.dup2(slave, target)
        if slave > 2:
            os.close(slave)
        os.execve(shell, [shell, "--norc", "--noprofile"], env)
    except BaseException:
        os._exit(127)


def _terminate(master: int, child: int) -> None:
    """Close the terminal and make sure the whole process group is gone."""
    try:
        os.close(master)
    except OSError:
        pass
    try:
        os.killpg(child, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    deadline = time.monotonic() + _GRACE_S
    while time.monotonic() < deadline:
        try:
            done, _ = os.waitpid(child, os.WNOHANG)
        except ChildProcessError:
            return
        if done:
            return
        time.sleep(0.01)
    try:
        os.killpg(child, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.waitpid(child, 0)
    except ChildProcessError:
        pass


class _Session:
    """One tape playing against one terminal."""

    def __init__(self, *, tape: Tape, layout: Layout, rules: Sequence[Rule]) -> None:
        """Prepare the screen, the clock and the rewriter for a session."""
        self.tape = tape
        self.screen = TerminalScreen(cols=layout.cols, rows=layout.rows)
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.rewriter = StreamRewriter(rules)
        self.now_ms = 0
        self.stamp_ms = 0
        self.hidden = False
        self.total_bytes = 0
        self.wall_deadline = 0.0

    def play(self, master: int, child: int) -> Recording:
        """Run every instruction, then return the finished recording."""
        budget = min(MAX_WALL_MS, self.tape.scheduled_ms() + 60_000)
        self.wall_deadline = time.monotonic() + budget / 1000
        self.drain(master, _STARTUP_MS / 1000, settle=True, expect=True, patience=10.0)
        self.now_ms = BOOT_MS
        for instruction in self.tape.instructions:
            self.step(master, instruction)
        self.drain(master, _SETTLE_MS / 1000, settle=True)
        self.feed(self.rewriter.flush())
        return self.screen.snapshot(duration_ms=self.now_ms)

    def step(self, master: int, instruction: object) -> None:
        """Perform one instruction."""
        speed = self.tape.settings.typing_speed_ms
        match instruction:
            case TypeText(_, text):
                for char in text:
                    self.write(master, char)
                    self.now_ms += speed
                    self.stamp_ms = self.now_ms
                    self.drain(master, speed / 1000, expect=True, patience=_ECHO_S)
            case PressKey(_, key):
                self.write(master, KEY_MAP[key])
                self.stamp_ms = self.now_ms
                self.drain(master, speed / 1000)
            case PressCtrl(_, letter):
                self.write(master, ctrl_code(letter))
                self.stamp_ms = self.now_ms
                self.drain(master, speed / 1000)
            case SleepFor(_, duration_ms):
                self.stamp_ms = self.now_ms
                self.drain(master, duration_ms / 1000, settle=True)
                self.now_ms += duration_ms
            case SetHidden(_, hidden):
                self.stamp_ms = self.now_ms
                self.drain(master, _SETTLE_MS / 1000, settle=True)
                self.hidden = hidden

    def write(self, master: int, text: str) -> None:
        """Send text to the terminal."""
        data = text.encode("utf-8")
        try:
            while data:
                data = data[os.write(master, data) :]
        except OSError as exc:
            raise DriverError(f"could not write to the terminal: {exc}") from exc

    def drain(
        self,
        master: int,
        seconds: float,
        *,
        settle: bool = False,
        expect: bool = False,
        patience: float = _MAX_SETTLE_S,
    ) -> None:
        """Read output for a span of real time, feeding it to the screen.

        The span is a floor, not a ceiling. With ``settle`` the read
        continues until the terminal has been quiet for a moment. With
        ``expect`` it continues until something has arrived at all, which is
        how the session waits for a slow shell to print its prompt and for a
        typed character to be echoed back. Both are bounded by ``patience``,
        so a program that says nothing cannot hold the session open.

        Waiting longer costs real time and changes no timestamp, because the
        recording's clock comes from the tape rather than from the machine.
        A loaded machine therefore records the same session as an idle one
        instead of cutting output off or stamping it late.

        Parameters
        ----------
        master : int
            The terminal descriptor.
        seconds : float
            How long to read for at minimum.
        settle : bool, optional
            Whether to keep reading until output stops.
        expect : bool, optional
            Whether to keep reading until output starts.
        patience : float, optional
            Longest extra wait either of those may add.
        """
        start = time.monotonic()
        end = start + seconds
        limit = end + (patience if settle or expect else 0.0)
        last_data = start
        seen = False
        while True:
            now = time.monotonic()
            if now > self.wall_deadline:
                raise DriverError("session ran longer than its time budget")
            if now >= limit:
                self.feed(self.rewriter.flush())
                return
            if (
                now >= end
                and (not expect or seen)
                and (not settle or now - last_data >= _QUIET_S)
            ):
                self.feed(self.rewriter.flush())
                return
            try:
                ready, _, _ = select.select([master], [], [], 0.02)
            except InterruptedError:
                continue
            if not ready:
                continue
            seen = True
            last_data = time.monotonic()
            try:
                chunk = os.read(master, READ_CHUNK)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    return
                raise DriverError(f"could not read from the terminal: {exc}") from exc
            if not chunk:
                return
            self.total_bytes += len(chunk)
            if self.total_bytes > MAX_PTY_BYTES:
                raise DriverError(
                    f"session produced more than {MAX_PTY_BYTES} bytes of output"
                )
            self.feed(self.rewriter.feed(self.decoder.decode(chunk)))

    def feed(self, text: str) -> None:
        """Apply masked output to the screen unless recording is paused."""
        if not text or self.hidden:
            return
        try:
            self.screen.feed(text, time_ms=self.stamp_ms)
        except ValueError as exc:
            raise DriverError(str(exc)) from exc
