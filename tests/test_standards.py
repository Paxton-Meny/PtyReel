"""Tests that enforce the house style the gate has no linter for.

There is no formatter, no linter and no type checker in the quality gate, so
the rules that would normally be a tool's job are asserted here instead. A
failure names the file and the line, the way a linter would.
"""

from __future__ import annotations

import ast
import tokenize
import unittest
from pathlib import Path

from support import REPO_ROOT, SRC_ROOT, TESTS_ROOT, PtyReelTestCase

PACKAGE_ROOT = SRC_ROOT / "ptyreel"
SOURCES = sorted(PACKAGE_ROOT.glob("*.py"))
TEST_SOURCES = sorted(TESTS_ROOT.glob("*.py"))
ALL_SOURCES = SOURCES + TEST_SOURCES
FORBIDDEN_REFERENCES = ("LAWS.md", "_STANDARDS.md", "orig/")


def parsed(path: Path) -> ast.Module:
    """Parse one source file."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class ModuleShapeTest(PtyReelTestCase):
    """Every module opens the same way."""

    def test_sources_were_found(self) -> None:
        """A glob that matched nothing would make this file pass silently."""
        self.assertGreater(len(SOURCES), 10)
        self.assertGreater(len(TEST_SOURCES), 10)

    def test_docstring_then_future_import(self) -> None:
        """Explanation first, then the annotation behaviour every module uses."""
        for path in ALL_SOURCES:
            with self.subTest(path=path.name):
                body = parsed(path).body
                self.assertIsNotNone(ast.get_docstring(ast.Module(body, [])))
                second = body[1]
                self.assertIsInstance(second, ast.ImportFrom)
                self.assertEqual(second.module, "__future__")
                self.assertEqual([alias.name for alias in second.names], ["annotations"])

    def test_package_modules_declare_their_surface(self) -> None:
        """An explicit list says what a module offers."""
        for path in SOURCES:
            with self.subTest(path=path.name):
                names = [
                    target.id
                    for node in parsed(path).body
                    if isinstance(node, ast.Assign)
                    for target in node.targets
                    if isinstance(target, ast.Name)
                ]
                self.assertIn("__all__", names, f"{path.name} has no __all__")


class DocstringTest(PtyReelTestCase):
    """Explanation lives in docstrings, because comments are not allowed."""

    def test_everything_is_documented(self) -> None:
        """Classes and functions all carry a docstring, private ones too."""
        for path in ALL_SOURCES:
            for node in ast.walk(parsed(path)):
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    continue
                with self.subTest(path=path.name, name=node.name, line=node.lineno):
                    self.assertIsNotNone(
                        ast.get_docstring(node),
                        f"{path.name}:{node.lineno}: {node.name} has no docstring",
                    )

    def test_no_comments_in_the_package(self) -> None:
        """A comment means an explanation is in the wrong place."""
        for path in SOURCES:
            with self.subTest(path=path.name):
                with path.open(encoding="utf-8") as handle:
                    for token in tokenize.generate_tokens(handle.readline):
                        if token.type == tokenize.COMMENT:
                            self.fail(
                                f"{path.name}:{token.start[0]}: comment found, "
                                "move the explanation into a docstring"
                            )


class AnnotationTest(PtyReelTestCase):
    """Every signature is annotated, since nothing else checks types."""

    def test_arguments_and_returns(self) -> None:
        """Each parameter and each return carries a type."""
        for path in SOURCES:
            for node in ast.walk(parsed(path)):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                with self.subTest(path=path.name, name=node.name, line=node.lineno):
                    self.assertIsNotNone(
                        node.returns,
                        f"{path.name}:{node.lineno}: {node.name} has no return type",
                    )
                    arguments = [
                        *node.args.posonlyargs,
                        *node.args.args,
                        *node.args.kwonlyargs,
                    ]
                    for extra in (node.args.vararg, node.args.kwarg):
                        if extra is not None:
                            arguments.append(extra)
                    for argument in arguments:
                        if argument.arg in ("self", "cls"):
                            continue
                        self.assertIsNotNone(
                            argument.annotation,
                            f"{path.name}:{node.lineno}: {node.name} "
                            f"argument {argument.arg} has no type",
                        )


class ConstantTest(PtyReelTestCase):
    """Module level names that are not classes or functions are constants."""

    def test_upper_case(self) -> None:
        """A lower case module level assignment reads like mutable state."""
        for path in SOURCES:
            for node in parsed(path).body:
                targets: list[ast.expr] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AnnAssign):
                    annotation = node.annotation
                    if isinstance(annotation, ast.Name) and annotation.id == "TypeAlias":
                        continue
                    targets = [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    name = target.id
                    if name.startswith("__") and name.endswith("__"):
                        continue
                    with self.subTest(path=path.name, name=name):
                        self.assertEqual(
                            name.lstrip("_"),
                            name.lstrip("_").upper(),
                            f"{path.name}:{node.lineno}: {name} is not a constant name",
                        )


class HygieneTest(PtyReelTestCase):
    """Nothing in the repository points at files that are not in it."""

    def tracked(self) -> list[Path]:
        """Return the files a reader of the repository would see."""
        roots = ("src", "tests", "demos", ".github", "hooks")
        found: list[Path] = []
        for root in roots:
            base = REPO_ROOT / root
            if base.exists():
                found.extend(
                    path for path in base.rglob("*") if path.is_file()
                )
        found.extend(
            REPO_ROOT / name
            for name in ("README.md", "CHANGELOG.md", "CONTRIBUTING.md", "action.yml")
            if (REPO_ROOT / name).exists()
        )
        return found

    def test_no_dangling_references(self) -> None:
        """Local-only files are never named by anything committed.

        This module is skipped, because it has to spell the names out in
        order to look for them.
        """
        for path in self.tracked():
            if path.suffix == ".svg" or path.name.endswith(".pyc"):
                continue
            if path.name == Path(__file__).name:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for reference in FORBIDDEN_REFERENCES:
                if reference in text:
                    self.fail(f"{path.name} names a local-only path: {reference}")

    def test_no_test_uses_a_sleep(self) -> None:
        """Waiting on a clock is what makes a suite flake."""
        for path in TEST_SOURCES:
            for node in ast.walk(parsed(path)):
                if isinstance(node, ast.Attribute) and node.attr == "sleep":
                    self.fail(f"{path.name}:{node.lineno}: tests must not sleep")


if __name__ == "__main__":
    unittest.main()
