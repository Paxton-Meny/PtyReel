"""Tests for the command line.

The entry point returns an exit code rather than raising, so every case runs
in this process with its output captured. No subprocess is needed.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from support import HAS_BASH, POSIX_ONLY, PtyReelTestCase

from ptyreel.__main__ import main

TAPE = 'Output out/demo.svg\nSet Width 700\nSet Height 320\nType "echo cli-ok"\nEnter\nSleep 300ms\n'


class CommandLineTest(PtyReelTestCase):
    """Arguments, exit codes and the two output streams."""

    def setUp(self) -> None:
        """Give each case its own workspace holding one tape."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "demo.tape").write_text(TAPE, encoding="utf-8")

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        """Run the command line and capture both streams."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([*args, "--workspace", str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def test_check_accepts_a_valid_tape(self) -> None:
        """Checking says nothing and writes nothing."""
        code, out, err = self.run_cli("--check", "demo.tape")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertFalse((self.root / "out").exists())

    def test_check_reports_a_broken_tape(self) -> None:
        """A parse error names the file and the line on the error stream."""
        (self.root / "bad.tape").write_text(
            "Output out/a.svg\nEnter\nWat\n", encoding="utf-8"
        )
        code, out, err = self.run_cli("--check", "bad.tape")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("bad.tape:3: unknown directive: Wat", err)
        self.assertTrue(err.startswith("ptyreel: "))

    def test_missing_tape(self) -> None:
        """A path that is not there says so."""
        code, _, err = self.run_cli("--check", "nope.tape")
        self.assertEqual(code, 1)
        self.assertIn("nope.tape", err)

    def test_escaping_output_is_refused(self) -> None:
        """An override that leaves the workspace fails before anything runs."""
        code, _, err = self.run_cli("--check", "demo.tape", "--output", "../x.svg")
        self.assertEqual(code, 1)
        self.assertIn("--output", err)

    def test_output_needs_a_single_tape(self) -> None:
        """One override cannot serve two tapes."""
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("demo.tape", "demo.tape", "--output", "a.svg")
        self.assertEqual(caught.exception.code, 2)

    def test_help_exits_cleanly(self) -> None:
        """Asking for help is not an error."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as caught:
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("usage:", out.getvalue())

    @POSIX_ONLY
    @HAS_BASH
    def test_render_writes_the_document(self) -> None:
        """A full run reports the path it wrote, relative to the workspace."""
        code, out, err = self.run_cli("demo.tape")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "out/demo.svg\n")
        document = (self.root / "out" / "demo.svg").read_text(encoding="utf-8")
        self.assertIn("cli-ok", document)
        self.assert_svg_sane(document)

    @POSIX_ONLY
    @HAS_BASH
    def test_output_override_is_honoured(self) -> None:
        """The override wins over the tape's own path."""
        code, out, err = self.run_cli("demo.tape", "--output", "elsewhere/x.svg")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "elsewhere/x.svg\n")
        self.assertTrue((self.root / "elsewhere" / "x.svg").exists())

    @POSIX_ONLY
    @HAS_BASH
    def test_two_tapes_report_two_paths(self) -> None:
        """Paths come out in the order they were given."""
        (self.root / "second.tape").write_text(
            TAPE.replace("out/demo.svg", "out/second.svg"), encoding="utf-8"
        )
        code, out, err = self.run_cli("demo.tape", "second.tape")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "out/demo.svg\nout/second.svg\n")

    @POSIX_ONLY
    @HAS_BASH
    def test_rendering_is_reproducible(self) -> None:
        """Running the same tape twice writes the same bytes."""
        self.run_cli("demo.tape")
        first = (self.root / "out" / "demo.svg").read_bytes()
        self.run_cli("demo.tape")
        second = (self.root / "out" / "demo.svg").read_bytes()
        self.assertEqual(first, second)

    def test_default_workspace_is_the_current_directory(self) -> None:
        """Leaving the workspace out uses where the tool was run from."""
        out, err = io.StringIO(), io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["--check", "demo.tape"]), 0)


if __name__ == "__main__":
    unittest.main()
