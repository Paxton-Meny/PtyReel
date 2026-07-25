"""Tests over the files a consumer and a maintainer read.

The standard library has no parser for the action or the workflow, so these
are text level assertions. They are worth having anyway: each one pins a rule
that is easy to break by accident and expensive to notice late.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from support import REPO_ROOT, PtyReelTestCase

from ptyreel.parse import parse_tape

ACTION = REPO_ROOT / "action.yml"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
HOOKS = REPO_ROOT / "hooks"
DEMOS = REPO_ROOT / "demos"
GATE_STEPS = ("-m compileall -q src tests", "-m unittest discover -s tests")
BANNED_WORDS = (
    "delve",
    "leverage",
    "robust",
    "seamless",
    "crucial",
    "comprehensive",
    "cutting-edge",
    "empower",
    "journey",
    "landscape",
)
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


class DemoTest(PtyReelTestCase):
    """Every shipped tape parses, so a broken demo cannot be committed."""

    def test_demos_exist(self) -> None:
        """A glob that matched nothing would make this pass silently."""
        self.assertTrue(list(DEMOS.glob("*.tape")))

    def test_demos_parse(self) -> None:
        """Checking a tape needs no terminal, so this runs anywhere."""
        for path in sorted(DEMOS.glob("*.tape")):
            with self.subTest(tape=path.name):
                parse_tape(path.read_text(encoding="utf-8"), source=path.name)


class ActionTest(PtyReelTestCase):
    """The action interface says what the README says."""

    def text(self) -> str:
        """Return the action definition."""
        return ACTION.read_text(encoding="utf-8")

    def test_action_exists(self) -> None:
        """A missing file would make every other assertion vacuous."""
        self.assertTrue(ACTION.exists())

    def test_no_third_party_steps(self) -> None:
        """This repository composes only its own run steps."""
        for number, line in enumerate(self.text().splitlines(), start=1):
            self.assertFalse(
                line.strip().startswith("uses:"), f"action.yml:{number}: uses: step"
            )

    def test_declares_its_interface(self) -> None:
        """The inputs and the output the README documents are all present."""
        text = self.text()
        self.assertIn("using: composite", text)
        for name in ("tape:", "output:", "check:", "workspace:", "svg-path:"):
            self.assertIn(name, text)

    def test_expressions_never_reach_a_shell_body(self) -> None:
        """Inputs arrive through the environment, so nothing is interpolated."""
        for number, line in enumerate(self.text().splitlines(), start=1):
            if "${{" not in line:
                continue
            self.assertRegex(
                line,
                r"^\s*[A-Za-z0-9_.-]+:\s",
                f"action.yml:{number}: expression outside a mapping value",
            )


class WorkflowTest(PtyReelTestCase):
    """Continuous integration runs the gate and nothing else."""

    def workflows(self) -> list[Path]:
        """Return every workflow file."""
        return sorted(WORKFLOWS.glob("*.yml"))

    def test_workflow_exists(self) -> None:
        """There is at least one, and it is the gate."""
        self.assertTrue(self.workflows())

    def test_no_third_party_actions(self) -> None:
        """Checkout is done with git, so no action is trusted."""
        for path in self.workflows():
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                self.assertFalse(
                    line.strip().startswith("uses:"), f"{path.name}:{number}: uses: step"
                )

    def test_hardening(self) -> None:
        """Read-only, time-bounded, and superseded by a newer run."""
        text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        for needle in ("permissions: {}", "contents: read", "timeout-minutes:", "cancel-in-progress: true"):
            self.assertIn(needle, text)

    def test_runs_exactly_the_gate(self) -> None:
        """The workflow has no checks of its own."""
        text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        for step in GATE_STEPS:
            self.assertIn(step, text)

    def test_expressions_never_reach_a_shell_body(self) -> None:
        """The token is passed through the environment, never interpolated."""
        for path in self.workflows():
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "${{" not in line:
                    continue
                self.assertRegex(
                    line,
                    r"^\s*[A-Za-z0-9_.-]+:\s",
                    f"{path.name}:{number}: expression outside a mapping value",
                )


class HookTest(PtyReelTestCase):
    """Local hooks run the same gate and never change anything."""

    def test_hooks_exist(self) -> None:
        """Both points a contributor would want covered."""
        for name in ("pre-commit", "pre-push"):
            self.assertTrue((HOOKS / name).exists(), f"hooks/{name} is missing")

    def test_hooks_run_the_gate(self) -> None:
        """A hook that ran something else would drift from the workflow."""
        for name in ("pre-commit", "pre-push"):
            text = (HOOKS / name).read_text(encoding="utf-8")
            for step in GATE_STEPS:
                self.assertIn(step, text)

    def test_hooks_report_only(self) -> None:
        """Nothing here stages, formats or rewrites."""
        for name in ("pre-commit", "pre-push"):
            text = (HOOKS / name).read_text(encoding="utf-8")
            for forbidden in ("git add", "git commit", "git push", "--fix"):
                self.assertNotIn(forbidden, text, f"hooks/{name} changes things")


class ProseTest(PtyReelTestCase):
    """Documentation follows the house style."""

    def documents(self) -> list[Path]:
        """Return the prose a reader of the repository meets."""
        found = [path for path in REPO_ROOT.glob("*.md")]
        found.extend((REPO_ROOT / ".github").rglob("*.md"))
        return sorted(found)

    def test_no_filler_words(self) -> None:
        """These words carry no information and read as padding."""
        for path in self.documents():
            text = path.read_text(encoding="utf-8").lower()
            for word in BANNED_WORDS:
                with self.subTest(path=path.name, word=word):
                    self.assertIsNone(
                        re.search(rf"\b{re.escape(word)}\b", text),
                        f"{path.name} uses {word}",
                    )

    def test_no_emoji(self) -> None:
        """Prose reads the same everywhere, including in a terminal."""
        for path in self.documents():
            with self.subTest(path=path.name):
                self.assertIsNone(EMOJI.search(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
