"""Tests for workspace containment and atomic writing.

The string rules run everywhere, so they are checked on every platform. The
descriptor walk and the rename need POSIX, so those cases are skipped
elsewhere rather than weakened to fit.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from support import POSIX_ONLY, PtyReelTestCase

from ptyreel.errors import PathSecurityError
from ptyreel.paths import (
    MAX_SVG_BYTES,
    open_parent,
    read_text_at,
    validate_relative_path,
    write_atomic,
)

REJECTED: tuple[tuple[str, str], ...] = (
    ("absolute", "/tmp/x.svg"),
    ("network_share", "//host/share/x.svg"),
    ("drive_absolute", "C:\\x.svg"),
    ("drive_relative", "C:x.svg"),
    ("home", "~/x.svg"),
    ("parent", "../x.svg"),
    ("parent_inside", "a/../b.svg"),
    ("current", "./x.svg"),
    ("double_slash", "a//b.svg"),
    ("trailing_slash", "a/b.svg/"),
    ("git_directory", ".git/x.svg"),
    ("forge_directory", ".github/x.svg"),
    ("dotfile", ".hidden.svg"),
    ("backslash", "a\\b.svg"),
    ("null_byte", "x.svg\x00"),
    ("control_character", "x\ty.svg"),
    ("wrong_suffix", "x.png"),
    ("suffix_only", ".svg"),
    ("empty", ""),
    ("long_component", "a" * 300 + ".svg"),
    ("too_deep", "/".join("abcdefghijklmnopq") + ".svg"),
)


class ValidateTest(PtyReelTestCase):
    """String validation rejects a whole class of paths before any I/O."""

    def test_rejected(self) -> None:
        """Each case fails and says which path it failed on."""
        for name, raw in REJECTED:
            with self.subTest(case=name):
                with self.assertRaises(PathSecurityError) as caught:
                    validate_relative_path(raw, source="t.tape", line=2, suffix=".svg")
                self.assertEqual(caught.exception.path, raw)
                self.assertEqual(caught.exception.line, 2)

    def test_accepted(self) -> None:
        """Ordinary relative paths split into components."""
        for raw, expected in (
            ("a.svg", ("a.svg",)),
            ("docs/demo.svg", ("docs", "demo.svg")),
            ("a/b/c-d_e.svg", ("a", "b", "c-d_e.svg")),
            ("out/a.b.svg", ("out", "a.b.svg")),
        ):
            with self.subTest(path=raw):
                self.assertEqual(
                    validate_relative_path(raw, source="t.tape", suffix=".svg"),
                    expected,
                )

    def test_components_are_plain(self) -> None:
        """The result can be pasted into a shell line without quoting."""
        parts = validate_relative_path("docs/a-b_c.svg", source="t", suffix=".svg")
        for part in parts:
            self.assertRegex(part, r"\A[A-Za-z0-9._-]+\Z")

    def test_tape_suffix(self) -> None:
        """The same rules apply to the input path."""
        self.assertEqual(
            validate_relative_path("demos/a.tape", source="cli", suffix=".tape"),
            ("demos", "a.tape"),
        )
        with self.assertRaises(PathSecurityError):
            validate_relative_path("demos/a.svg", source="cli", suffix=".tape")


@POSIX_ONLY
class WalkTest(PtyReelTestCase):
    """The descriptor walk refuses to leave the workspace."""

    def setUp(self) -> None:
        """Give each case its own workspace."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def walk(self, path: str, *, create: bool = False) -> tuple[int, str]:
        """Open the parent of a path inside the workspace."""
        parts = validate_relative_path(path, source="t.tape", suffix=".svg")
        parent, name = open_parent(str(self.root), parts, source="t.tape", create=create)
        self.addCleanup(os.close, parent)
        return parent, name

    def test_writes_land_inside_the_workspace(self) -> None:
        """A nested path is created and written where it was asked for."""
        parent, name = self.walk("docs/assets/demo.svg", create=True)
        write_atomic(parent, name, "<svg/>\n")
        self.assertEqual(
            (self.root / "docs" / "assets" / "demo.svg").read_text(encoding="utf-8"),
            "<svg/>\n",
        )

    def test_missing_directory_without_create(self) -> None:
        """Nothing is created unless the caller asked for it."""
        with self.assertRaises(PathSecurityError):
            self.walk("docs/demo.svg")

    def test_symlinked_directory_is_refused(self) -> None:
        """A link in the middle of the path cannot redirect the write."""
        outside = Path(self.temporary.name).parent / "ptyreel-outside"
        outside.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        os.symlink(outside, self.root / "docs", target_is_directory=True)
        with self.assertRaises(PathSecurityError) as caught:
            self.walk("docs/demo.svg", create=True)
        self.assertIn("symbolic link", str(caught.exception))

    def test_symlinked_destination_is_replaced_not_followed(self) -> None:
        """A link at the destination is overwritten, not written through."""
        target = self.root / "real.txt"
        target.write_text("original", encoding="utf-8")
        os.symlink(target, self.root / "demo.svg")
        parent, name = self.walk("demo.svg")
        write_atomic(parent, name, "<svg/>\n")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")
        self.assertFalse((self.root / "demo.svg").is_symlink())

    def test_write_leaves_no_temporary_behind(self) -> None:
        """A finished write leaves exactly one file."""
        parent, name = self.walk("demo.svg")
        write_atomic(parent, name, "<svg/>\n")
        self.assertEqual([entry.name for entry in self.root.iterdir()], ["demo.svg"])

    def test_oversized_document_is_refused(self) -> None:
        """The size cap fires before anything reaches the disk."""
        parent, name = self.walk("demo.svg")
        with self.assertRaises(ValueError):
            write_atomic(parent, name, "x" * (MAX_SVG_BYTES + 1))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_read_respects_its_limit(self) -> None:
        """A file larger than the limit is refused rather than truncated."""
        (self.root / "big.tape").write_text("x" * 100, encoding="utf-8")
        parts = validate_relative_path("big.tape", source="cli", suffix=".tape")
        parent, name = open_parent(str(self.root), parts, source="cli")
        self.addCleanup(os.close, parent)
        self.assertEqual(len(read_text_at(parent, name, limit=100)), 100)
        with self.assertRaises(ValueError):
            read_text_at(parent, name, limit=99)


if __name__ == "__main__":
    unittest.main()
