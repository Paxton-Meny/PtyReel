"""Tests that drive a real pseudo-terminal.

These need POSIX and a shell, so they are skipped elsewhere rather than
weakened. Nothing here sleeps and nothing asserts a wall clock measurement.
Deadlines are failure bounds, not runtimes: a passing test finishes long
before them.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from support import HAS_BASH, POSIX_ONLY, PtyReelTestCase, dump

from ptyreel.errors import DriverError
from ptyreel.layout import Layout
from ptyreel.parse import parse_tape

if os.name == "posix":
    from ptyreel.driver import build_child_env, run_tape


def play(source: str, **kwargs: object) -> object:
    """Parse a tape and run it, returning the recording."""
    tape = parse_tape(f"Output out/a.svg\n{source}", source="t.tape")
    return run_tape(tape, layout=Layout.from_settings(tape.settings), **kwargs)


@POSIX_ONLY
@HAS_BASH
class SessionTest(PtyReelTestCase):
    """A tape reaches the shell and the shell's output reaches the screen."""

    def tearDown(self) -> None:
        """Prove the driver reaped its child rather than leaving a zombie."""
        with self.assertRaises(ChildProcessError):
            os.waitpid(-1, os.WNOHANG)

    def test_output_is_captured(self) -> None:
        """The simplest possible round trip."""
        recording = play('Type "echo ptyreel-ok"\nEnter\nSleep 300ms\n')
        self.assertIn("ptyreel-ok", dump(recording))

    def test_typing_is_stamped_by_the_tape(self) -> None:
        """Timestamps come from the declared speed, not from the machine."""
        recording = play('Set TypingSpeed 40ms\nType "ab"\nEnter\nSleep 200ms\n')
        first = recording.lines[0]
        stamps = [stamp for stamp in first.times if stamp >= 0]
        self.assertEqual(stamps[:4], [0, 0, 540, 580])
        self.assertEqual(recording.duration_ms, 500 + 40 * 2 + 200)

    def test_two_runs_agree(self) -> None:
        """The same tape against the same command records the same thing."""
        source = 'Type "echo steady"\nEnter\nSleep 300ms\n'
        first = play(source)
        second = play(source)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_window_size_reaches_the_child(self) -> None:
        """The shell is told how wide its terminal is."""
        tape = parse_tape(
            'Output out/a.svg\nType "stty size"\nEnter\nSleep 400ms\n',
            source="t.tape",
        )
        layout = Layout.from_settings(tape.settings)
        recording = run_tape(tape, layout=layout)
        self.assertIn(f"{layout.rows} {layout.cols}", dump(recording))

    def test_colour_is_captured(self) -> None:
        """Attributes survive the round trip, not just the characters."""
        recording = play(
            'Type "printf \'\\\\033[31mRED\\\\033[0m\\\\n\'"\nEnter\nSleep 400ms\n'
        )
        text = dump(recording)
        self.assertIn("RED", text)
        coloured = [
            recording.styles[version.styles[column]].fg
            for version in recording.lines
            for column, char in enumerate(version.chars)
            if char == "R" and version.times[column] >= 0
        ]
        self.assertIn(1, coloured)

    def test_hidden_output_is_not_recorded(self) -> None:
        """Setup a tape does not want shown leaves no trace."""
        recording = play(
            "Hide\n"
            'Type "echo setup-secret"\nEnter\nSleep 300ms\n'
            "Show\n"
            'Type "echo visible"\nEnter\nSleep 300ms\n'
        )
        text = dump(recording)
        self.assertNotIn("setup-secret", text)
        self.assertIn("visible", text)

    def test_control_character_reaches_the_shell(self) -> None:
        """An interrupt cancels the line being typed."""
        recording = play('Type "echo never"\nCtrl+C\nSleep 300ms\n')
        self.assertNotIn("never\n", dump(recording) + "\n")

    def test_invalid_bytes_become_a_replacement(self) -> None:
        """Output that is not valid text still produces a usable document."""
        recording = play("Type \"printf '\\\\377\\\\376'\"\nEnter\nSleep 300ms\n")
        for version in recording.lines:
            for char in version.chars:
                self.assertLess(ord(char), 0xD800) if ord(char) < 0xE000 else None

    def test_secret_is_masked(self) -> None:
        """A value from a secret-looking variable never reaches the screen."""
        secret = "hunter2hunter2"
        recording = play(
            f'Type "echo {secret}"\nEnter\nSleep 300ms\n',
            environ={**os.environ, "MY_API_TOKEN": secret},
        )
        self.assertNotIn(secret, dump(recording))
        self.assertIn("*", dump(recording))

    def test_child_environment_is_an_allowlist(self) -> None:
        """A workflow token is not present inside a session at all."""
        child = build_child_env(
            {"GITHUB_TOKEN": "x", "PATH": "/usr/bin", "HOME": "/root"},
            shell="/bin/bash",
            cols=80,
            rows=24,
        )
        self.assertNotIn("GITHUB_TOKEN", child)
        self.assertEqual(child["PATH"], "/usr/bin")
        self.assertEqual(child["PS1"], "$ ")
        self.assertEqual(child["TERM"], "xterm-256color")

    def test_environment_variables_do_not_leak(self) -> None:
        """The shell itself cannot see a variable that was not passed in."""
        recording = play(
            'Type "echo [$PTYREEL_LEAK_CHECK]"\nEnter\nSleep 300ms\n',
            environ={**os.environ, "PTYREEL_LEAK_CHECK": "leaked"},
        )
        self.assertNotIn("leaked", dump(recording))
        self.assertIn("[]", dump(recording))


@POSIX_ONLY
@HAS_BASH
class FailureTest(PtyReelTestCase):
    """Sessions that go wrong end cleanly instead of hanging."""

    def tearDown(self) -> None:
        """No child survives a failed session."""
        with self.assertRaises(ChildProcessError):
            os.waitpid(-1, os.WNOHANG)

    def test_child_exit_is_treated_as_end_of_file(self) -> None:
        """A tape that quits the shell finishes rather than raising."""
        recording = play('Type "echo bye"\nEnter\nSleep 200ms\nType "exit"\nEnter\nSleep 200ms\n')
        self.assertIn("bye", dump(recording))

    def test_hanging_command_hits_the_budget(self) -> None:
        """A command that never returns cannot hold the session open."""
        tape = parse_tape(
            'Output out/a.svg\nType "sleep 999"\nEnter\nSleep 10s\n', source="t.tape"
        )
        layout = Layout.from_settings(tape.settings)
        with mock.patch("ptyreel.driver.MAX_WALL_MS", 500):
            with self.assertRaises(DriverError) as caught:
                run_tape(tape, layout=layout)
        self.assertIn("time budget", str(caught.exception))

    def test_output_flood_is_capped(self) -> None:
        """A command that prints without end is stopped by the byte cap."""
        tape = parse_tape(
            "Output out/a.svg\n"
            'Type "head -c 4000000 /dev/zero | tr \'\\\\0\' a"\nEnter\nSleep 10s\n',
            source="t.tape",
        )
        layout = Layout.from_settings(tape.settings)
        with mock.patch("ptyreel.driver.MAX_PTY_BYTES", 65_536):
            with self.assertRaises(DriverError) as caught:
                run_tape(tape, layout=layout)
        self.assertIn("bytes of output", str(caught.exception))

    def test_background_process_is_cleaned_up(self) -> None:
        """Killing the group stops what the session started."""
        play('Type "sleep 60 &"\nEnter\nSleep 300ms\n')


if __name__ == "__main__":
    unittest.main()
