"""Tests for streaming text substitution."""

from __future__ import annotations

import unittest

from support import PtyReelTestCase

from ptyreel.rewrite import StreamRewriter, literal_rule, rewrite_text, word_rule


class LiteralRuleTest(PtyReelTestCase):
    """A literal rule matches wherever the needle appears."""

    def test_replaces_everywhere(self) -> None:
        """Including inside a longer word, which is the point of literal."""
        rules = [literal_rule("/home/alice", "/home/LocalUser")]
        self.assertEqual(
            rewrite_text("cd /home/alice/src", rules), "cd /home/LocalUser/src"
        )

    def test_replacement_is_written_literally(self) -> None:
        """A backslash in the replacement carries no meaning."""
        rules = [literal_rule("x", "\\1")]
        self.assertEqual(rewrite_text("x", rules), "\\1")

    def test_needle_is_escaped(self) -> None:
        """A needle containing regular expression syntax is still literal."""
        rules = [literal_rule("a.c", "Z")]
        self.assertEqual(rewrite_text("a.c abc", rules), "Z abc")


class WordRuleTest(PtyReelTestCase):
    """A word rule matches only where the needle stands alone."""

    def test_standalone_matches(self) -> None:
        """The output of whoami is a bare name on its own line."""
        rules = [word_rule("runner", "LocalUser")]
        for text, expected in (
            ("runner", "LocalUser"),
            ("runner\n", "LocalUser\n"),
            ("user: runner, ok", "user: LocalUser, ok"),
            ("(runner)", "(LocalUser)"),
        ):
            with self.subTest(text=text):
                self.assertEqual(rewrite_text(text, rules), expected)

    def test_embedded_occurrences_are_left_alone(self) -> None:
        """An account called runner must not rewrite runner.py."""
        rules = [word_rule("runner", "LocalUser")]
        for text in (
            "runner.py",
            "/home/runner/work",
            "test-runner",
            "runners",
            "myrunner",
            "runner@host",
        ):
            with self.subTest(text=text):
                self.assertEqual(rewrite_text(text, rules), text)


class OrderTest(PtyReelTestCase):
    """Rules apply in the order given, so the caller sets precedence."""

    def test_longest_first_wins(self) -> None:
        """A home path becomes the preset home, not a mangled user name."""
        rules = [
            literal_rule("/home/alice", "/home/LocalUser"),
            word_rule("alice", "LocalUser"),
        ]
        self.assertEqual(
            rewrite_text("/home/alice and alice", rules),
            "/home/LocalUser and LocalUser",
        )


class StreamTest(PtyReelTestCase):
    """The rewriter sees a match split across two reads."""

    def rules(self) -> list:
        """Return one literal rule to exercise the stream."""
        return [literal_rule("hunter2hunter2", "**************")]

    def test_split_across_chunks(self) -> None:
        """Holding a tail is what makes the second half match."""
        rewriter = StreamRewriter(self.rules())
        released = rewriter.feed("value=hunter2") + rewriter.feed("hunter2 end")
        released += rewriter.flush()
        self.assertNotIn("hunter2hunter2", released)
        self.assertEqual(released, "value=************** end")

    def test_nothing_is_lost(self) -> None:
        """Everything fed comes out, rewritten or not."""
        rewriter = StreamRewriter(self.rules())
        released = rewriter.feed("hello ") + rewriter.feed("world") + rewriter.flush()
        self.assertEqual(released, "hello world")

    def test_no_rules_passes_straight_through(self) -> None:
        """With nothing to do the rewriter adds no delay."""
        rewriter = StreamRewriter([])
        self.assertEqual(rewriter.feed("abc"), "abc")
        self.assertEqual(rewriter.flush(), "")

    def test_chunking_does_not_change_the_result(self) -> None:
        """Feeding one character at a time gives the same text."""
        text = "a /home/alice b /home/alice c"
        rules = [literal_rule("/home/alice", "/home/LocalUser")]
        whole = StreamRewriter(rules)
        piecewise = StreamRewriter(rules)
        expected = whole.feed(text) + whole.flush()
        actual = "".join(piecewise.feed(char) for char in text) + piecewise.flush()
        self.assertEqual(actual, expected)
        self.assertEqual(actual, "a /home/LocalUser b /home/LocalUser c")


if __name__ == "__main__":
    unittest.main()
