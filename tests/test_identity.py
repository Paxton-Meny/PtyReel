"""Tests for replacing the machine's identity with fixed stand-ins."""

from __future__ import annotations

import unittest
from unittest import mock

from support import PtyReelTestCase

from ptyreel.identity import IDENTITY_PRESETS, identity_environ, identity_rules
from ptyreel.rewrite import rewrite_text


class EnvironTest(PtyReelTestCase):
    """The variables a shell reads are pinned to the presets."""

    def test_values(self) -> None:
        """Home points at the session directory, the rest at the presets."""
        environ = identity_environ("/tmp/session-home")
        self.assertEqual(environ["HOME"], "/tmp/session-home")
        self.assertEqual(environ["USER"], IDENTITY_PRESETS["user"])
        self.assertEqual(environ["LOGNAME"], IDENTITY_PRESETS["user"])
        self.assertEqual(environ["HOSTNAME"], IDENTITY_PRESETS["host"])


class RuleTest(PtyReelTestCase):
    """Substitutions cover what the environment cannot reach."""

    def rules(self, **changes: str) -> list:
        """Build rules for a fixed pretend machine."""
        environ = {"HOME": "/home/alice", "USER": "alice"}
        environ.update(changes)
        return identity_rules(session_home="/tmp/ptyreel-home-xyz", environ=environ)

    def test_home_path_becomes_the_preset(self) -> None:
        """A path printed by pwd or by a tool reads as the preset home."""
        rewritten = rewrite_text("cd /home/alice/src", self.rules())
        self.assertEqual(rewritten, f"cd {IDENTITY_PRESETS['home']}/src")

    def test_session_home_becomes_the_preset(self) -> None:
        """The temporary directory never appears in the recording."""
        rewritten = rewrite_text("HOME=/tmp/ptyreel-home-xyz", self.rules())
        self.assertEqual(rewritten, f"HOME={IDENTITY_PRESETS['home']}")

    def test_bare_user_name_becomes_the_preset(self) -> None:
        """This is what whoami and id print, which no variable can change."""
        self.assertEqual(rewrite_text("alice", self.rules()), IDENTITY_PRESETS["user"])

    def test_user_name_inside_a_word_is_left_alone(self) -> None:
        """An account named after something common must not rewrite it."""
        for text in ("alice.py", "malice", "alice-bot", "alices"):
            with self.subTest(text=text):
                self.assertEqual(rewrite_text(text, self.rules()), text)

    def test_path_wins_over_bare_name(self) -> None:
        """The home path is replaced whole, not left half rewritten."""
        rewritten = rewrite_text("/home/alice", self.rules())
        self.assertEqual(rewritten, IDENTITY_PRESETS["home"])

    def test_very_short_names_are_left_alone(self) -> None:
        """At two characters the risk of rewriting unrelated text is worse."""
        rules = self.rules(USER="ab", HOME="/home/ab")
        self.assertEqual(rewrite_text("ab cd ab", rules), "ab cd ab")

    def test_a_preset_name_needs_no_rule(self) -> None:
        """Nothing to do when the account already matches the preset."""
        rules = identity_rules(
            session_home="/tmp/x",
            environ={"HOME": IDENTITY_PRESETS["home"], "USER": IDENTITY_PRESETS["user"]},
        )
        self.assertEqual(
            rewrite_text(IDENTITY_PRESETS["user"], rules), IDENTITY_PRESETS["user"]
        )

    def test_root_directory_is_never_substituted(self) -> None:
        """A home of / would otherwise rewrite every path in the output."""
        rules = identity_rules(session_home="/tmp/x", environ={"HOME": "/", "USER": "x"})
        self.assertEqual(rewrite_text("/usr/bin", rules), "/usr/bin")

    def test_full_host_name_is_substituted(self) -> None:
        """macOS answers hostname with name.local, so both forms need rules.

        The short form's rule stops at a dot on purpose, which is exactly why
        it cannot cover the full form on its own.
        """
        with mock.patch(
            "ptyreel.identity.socket.gethostname", return_value="mybox.local"
        ):
            rules = identity_rules(
                session_home="/tmp/x",
                environ={"HOME": "/home/alice", "USER": "alice"},
            )
        self.assertEqual(
            rewrite_text("mybox.local", rules), IDENTITY_PRESETS["host"]
        )
        self.assertEqual(rewrite_text("mybox", rules), IDENTITY_PRESETS["host"])
        self.assertEqual(rewrite_text("mybox.py", rules), "mybox.py")


if __name__ == "__main__":
    unittest.main()
