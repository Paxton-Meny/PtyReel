"""Tests for the tape grammar.

Every error case asserts the reported line number, and no case puts the
offending directive on the first line, because an off-by-one in the line
counter is invisible when the answer is always one.
"""

from __future__ import annotations

import unittest

from support import PtyReelTestCase

from ptyreel.errors import PathSecurityError, TapeError
from ptyreel.parse import parse_tape
from ptyreel.tape import (
    BOOT_MS,
    MAX_INSTRUCTIONS,
    PressCtrl,
    PressKey,
    SetHidden,
    SleepFor,
    TypeText,
)

HEAD = "# a tape\nOutput out/demo.svg\n"

PARSE_ERRORS: tuple[tuple[str, str, int | None, str], ...] = (
    ("unknown_directive", HEAD + "Wat\n", 3, "unknown directive: Wat"),
    ("unknown_setting", "Output a.svg\nSet Colour 3\n", 2, "unknown setting"),
    ("setting_wrong_type", "Output a.svg\nSet FontSize 15px\n", 2, "whole number"),
    ("setting_too_large", "Output a.svg\nSet FontSize 100\n", 2, "at most 40"),
    ("setting_too_small", "Output a.svg\nSet Width 100\n", 2, "at least 320"),
    ("unknown_theme", 'Output a.svg\nSet Theme "dracula"\n', 2, "unknown theme"),
    ("bad_boolean", "Output a.svg\nSet Loop maybe\n", 2, "true or false"),
    ("duplicate_setting", "Output a.svg\nSet Width 900\nSet Width 800\n", 3, "already set"),
    ("duration_no_unit", HEAD + "Enter\nSleep 500\n", 4, "duration"),
    ("duration_too_long", HEAD + "Enter\nSleep 60s\n", 4, "between 1ms and 30s"),
    ("duration_too_short", "Output a.svg\nSet TypingSpeed 0ms\n", 2, "at least 1"),
    ("sleep_missing_argument", HEAD + "Enter\nSleep\n", 4, "duration"),
    ("key_with_argument", HEAD + "Enter now\n", 3, "takes no argument"),
    ("unterminated_quote", HEAD + 'Type "hello\n', 3, "unterminated"),
    ("unknown_escape", HEAD + 'Type "a\\q"\n', 3, "unknown escape"),
    ("type_unquoted", HEAD + "Type hello\n", 3, "quoted string"),
    ("type_too_long", HEAD + 'Type "' + "x" * 1001 + '"\n', 3, "longer than 1000"),
    ("ctrl_digit", HEAD + "Enter\nCtrl+1\n", 4, "unknown directive"),
    ("ctrl_empty", HEAD + "Enter\nCtrl+\n", 4, "unknown directive"),
    ("ctrl_two_letters", HEAD + "Enter\nCtrl+ab\n", 4, "unknown directive"),
    ("set_after_action", HEAD + "Enter\nSleep 1s\nSet Width 900\n", 5, "before the first action"),
    ("output_after_action", HEAD + "Enter\nSleep 1s\nOutput b.svg\n", 5, "before the first action"),
    ("duplicate_output", "# t\n# t\nOutput a.svg\nOutput b.svg\n", 4, "already set"),
    ("output_absolute", "# t\nOutput /tmp/x.svg\n", 2, "absolute"),
    ("output_traversal", "# t\nOutput ../x.svg\n", 2, "not allowed"),
    ("output_dotfile", "# t\nOutput .git/x.svg\n", 2, "not allowed"),
    ("output_wrong_suffix", "# t\nOutput demo.png\n", 2, "must name a .svg file"),
    ("output_missing_argument", "# t\nOutput\n", 2, "needs a path"),
    ("show_without_hide", HEAD + "Enter\nShow\n", 4, "without a matching Hide"),
    ("hide_twice", HEAD + "Hide\nSleep 1s\nHide\n", 5, "already hidden"),
    ("hide_unclosed", HEAD + "Hide\nEnter\n", None, "never followed by Show"),
    ("no_output", "# just a comment\nEnter\n", None, "no Output directive"),
    ("require_bad_name", "Output a.svg\nRequire ../bin/sh\n", 2, "command name"),
)

PARSE_ACCEPTS: tuple[tuple[str, str], ...] = (
    ("hash_inside_quotes", 'Output a.svg\nType "a # b"\n'),
    ("trailing_comment", "Output a.svg  # where it goes\nEnter\n"),
    ("crlf_endings", "Output a.svg\r\nEnter\r\n"),
    ("byte_order_mark", "﻿Output a.svg\nEnter\n"),
    ("blank_lines", "\n\n   \nOutput a.svg\n\nEnter\n"),
    ("no_trailing_newline", "Output a.svg\nEnter"),
    ("quoted_output", 'Output "out/a.svg"\nEnter\n'),
)


class ErrorTableTest(PtyReelTestCase):
    """Every malformed tape reports the right message on the right line."""

    def test_errors(self) -> None:
        """Each case names the file, the line and the reason."""
        for name, source, line, fragment in PARSE_ERRORS:
            with self.subTest(case=name):
                with self.assertRaises(TapeError) as caught:
                    parse_tape(source, source="demo.tape")
                error = caught.exception
                self.assertEqual(error.line, line, str(error))
                self.assertEqual(error.source, "demo.tape")
                self.assertIn(fragment, str(error))
                self.assertTrue(str(error).startswith("demo.tape:"))

    def test_path_problems_are_path_errors(self) -> None:
        """An escaping output path raises the more specific class."""
        with self.assertRaises(PathSecurityError):
            parse_tape("# t\nOutput ../x.svg\n", source="demo.tape")


class AcceptedTest(PtyReelTestCase):
    """The cases that break a naive line splitter still parse."""

    def test_accepts(self) -> None:
        """None of these raise."""
        for name, source in PARSE_ACCEPTS:
            with self.subTest(case=name):
                parse_tape(source, source="demo.tape")

    def test_byte_order_mark_keeps_line_numbers(self) -> None:
        """A mark on the first line does not shift later reports."""
        with self.assertRaises(TapeError) as caught:
            parse_tape("﻿Output a.svg\nWat\n", source="demo.tape")
        self.assertEqual(caught.exception.line, 2)

    def test_hash_inside_quotes_is_text(self) -> None:
        """A comment marker inside a string belongs to the string."""
        tape = parse_tape('Output a.svg\nType "a # b"\n', source="demo.tape")
        self.assertEqual(tape.instructions[0], TypeText(2, "a # b"))


class GrammarTest(PtyReelTestCase):
    """Directives produce the instructions they promise."""

    def test_every_instruction_kind(self) -> None:
        """One tape exercises the whole action vocabulary."""
        source = (
            "Output out/a.svg\n"
            'Type "ls -la"\n'
            "Enter\n"
            "Ctrl+C\n"
            "Sleep 1500ms\n"
            "Hide\n"
            "Tab\n"
            "Show\n"
        )
        tape = parse_tape(source, source="demo.tape")
        self.assertEqual(
            tape.instructions,
            (
                TypeText(2, "ls -la"),
                PressKey(3, "ENTER"),
                PressCtrl(4, "c"),
                SleepFor(5, 1500),
                SetHidden(6, True),
                PressKey(7, "TAB"),
                SetHidden(8, False),
            ),
        )

    def test_durations(self) -> None:
        """Both units are accepted and converted to milliseconds."""
        for literal, expected in (("1ms", 1), ("250ms", 250), ("2s", 2000), ("1.5s", 1500)):
            with self.subTest(literal=literal):
                tape = parse_tape(
                    f"Output a.svg\nSleep {literal}\n", source="demo.tape"
                )
                self.assertEqual(tape.instructions[0], SleepFor(2, expected))

    def test_escapes_in_typed_text(self) -> None:
        """The four escapes resolve, and a doubled backslash stays literal."""
        tape = parse_tape(
            'Output a.svg\nType "a\\nb\\tc\\"d\\\\ne"\n', source="demo.tape"
        )
        self.assertEqual(tape.instructions[0].text, 'a\nb\tc"d\\ne')

    def test_settings_are_collected(self) -> None:
        """Every setting kind reaches the right field."""
        source = (
            "Output a.svg\n"
            'Set Shell "bash"\n'
            "Set FontSize 18\n"
            "Set Width 1000\n"
            "Set Height 600\n"
            "Set Padding 12\n"
            "Set TypingSpeed 35ms\n"
            'Set Theme "github-light"\n'
            'Set Title "a demo"\n'
            "Set Loop false\n"
            "Set LoopDelay 4s\n"
            "Set MaskSecrets false\n"
        )
        settings = parse_tape(source, source="demo.tape").settings
        self.assertEqual(settings.font_size, 18)
        self.assertEqual(settings.width, 1000)
        self.assertEqual(settings.height, 600)
        self.assertEqual(settings.padding, 12)
        self.assertEqual(settings.typing_speed_ms, 35)
        self.assertEqual(settings.theme, "github-light")
        self.assertEqual(settings.title, "a demo")
        self.assertFalse(settings.loop)
        self.assertEqual(settings.loop_delay_ms, 4000)
        self.assertFalse(settings.mask_secrets)

    def test_requires_carry_lines(self) -> None:
        """A missing command can be reported against its own line."""
        tape = parse_tape(
            "Output a.svg\nRequire git\nRequire jq\n", source="demo.tape"
        )
        self.assertEqual(tape.requires, (("git", 2), ("jq", 3)))

    def test_scheduled_time_counts_typing_and_sleeping(self) -> None:
        """The declared timeline is what the renderer will use."""
        tape = parse_tape(
            'Output a.svg\nSet TypingSpeed 50ms\nType "abcd"\nEnter\nSleep 2s\n',
            source="demo.tape",
        )
        self.assertEqual(tape.scheduled_ms(), BOOT_MS + 4 * 50 + 2000)


class LimitTest(PtyReelTestCase):
    """The declared limits fire with a message a tape author can act on."""

    def test_instruction_count(self) -> None:
        """A tape stops being accepted past the instruction limit."""
        source = "Output a.svg\n" + "Enter\n" * (MAX_INSTRUCTIONS + 1)
        with self.assertRaises(TapeError) as caught:
            parse_tape(source, source="demo.tape")
        self.assertIn(f"more than {MAX_INSTRUCTIONS}", str(caught.exception))
        self.assertEqual(caught.exception.line, MAX_INSTRUCTIONS + 2)

    def test_scheduled_duration(self) -> None:
        """Declared timing that adds up past the cap is refused."""
        source = "Output a.svg\n" + "Sleep 30s\n" * 5
        with self.assertRaises(TapeError) as caught:
            parse_tape(source, source="demo.tape")
        self.assertIn("declared timing", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
