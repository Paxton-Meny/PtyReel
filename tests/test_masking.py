"""Tests for secret detection and redaction."""

from __future__ import annotations

import unittest

from support import PtyReelTestCase, dump

from ptyreel.masking import (
    StreamMasker,
    collect_secrets,
    mask_recording,
    mask_text,
    secret_forms,
)
from ptyreel.screen import TerminalScreen

SECRET = "hunter2hunter2"


class CollectTest(PtyReelTestCase):
    """Names are matched by segment, so ordinary variables are left alone."""

    def test_collected(self) -> None:
        """A secret-looking name with a substantial value is picked up."""
        for name in (
            "MY_API_TOKEN",
            "GITHUB_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "db-password",
            "SESSION_COOKIE",
            "SIGNING_KEY",
        ):
            with self.subTest(name=name):
                self.assertEqual(collect_secrets({name: SECRET}), (SECRET,))

    def test_ignored_names(self) -> None:
        """A name that merely contains a secret word is not a secret."""
        for name in ("MONKEY_COUNT", "PATH", "KEYBOARD_LAYOUT", "SSH_AUTH_SOCK"):
            with self.subTest(name=name):
                self.assertEqual(collect_secrets({name: SECRET}), ())

    def test_standard_variables_are_never_secrets(self) -> None:
        """These collide with the word list and appear on every machine.

        Masking one of them replaces correct output with asterisks and gives
        no clue why, so each is excluded by name or by the shape of its value.
        """
        ordinary = {
            "PWD": "/home/alice/projects/demo",
            "OLDPWD": "/home/alice",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "SESSION_MANAGER": "local/box:@/tmp/.ICE-unix/1234",
            "XDG_SESSION_DESKTOP": "gnome-session",
            "XDG_SESSION_ID": "seat0-session-12345",
        }
        for name, value in ordinary.items():
            with self.subTest(name=name):
                self.assertEqual(
                    collect_secrets({name: value}), (), f"{name} must not be masked"
                )

    def test_a_path_is_never_a_secret(self) -> None:
        """A value that reads as a filesystem path is left alone."""
        self.assertEqual(collect_secrets({"MY_TOKEN": "/var/run/something/long"}), ())

    def test_real_secrets_still_collected_alongside_them(self) -> None:
        """Narrowing the match must not stop it finding an actual secret."""
        found = collect_secrets(
            {
                "PWD": "/home/alice/projects/demo",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "MY_API_TOKEN": SECRET,
            }
        )
        self.assertEqual(found, (SECRET,))

    def test_ignored_values(self) -> None:
        """Values too short or too ordinary are not worth masking."""
        for value in ("short", "true", "FALSE", "1", "aaaaaaaaaa", "12345"):
            with self.subTest(value=value):
                self.assertEqual(collect_secrets({"MY_TOKEN": value}), ())

    def test_long_digit_strings_still_count(self) -> None:
        """A long number can still be a credential."""
        self.assertEqual(
            collect_secrets({"API_KEY": "1234567890123456"}), ("1234567890123456",)
        )


class FormsTest(PtyReelTestCase):
    """A value is masked in the shapes a shell pipeline can produce."""

    def test_encodings_are_covered(self) -> None:
        """Base64, percent encoding and hexadecimal all appear."""
        forms = secret_forms([SECRET])
        self.assertIn(SECRET, forms)
        self.assertIn("aHVudGVyMmh1bnRlcjI=", forms)
        self.assertIn("aHVudGVyMmh1bnRlcjI", forms)
        self.assertIn(SECRET.encode().hex(), forms)

    def test_longest_first(self) -> None:
        """Longer forms match before shorter ones overlap them."""
        forms = secret_forms([SECRET])
        self.assertEqual(list(forms), sorted(forms, key=lambda f: (-len(f), f)))

    def test_short_forms_are_dropped(self) -> None:
        """A form too short to be distinctive would mask ordinary text."""
        self.assertNotIn("abc", secret_forms(["abc"]))


class MaskTextTest(PtyReelTestCase):
    """Replacements keep the original length."""

    def test_length_is_preserved(self) -> None:
        """Column positions after a match must not move."""
        masked = mask_text(f"token={SECRET} done", secret_forms([SECRET]))
        self.assertNotIn(SECRET, masked)
        self.assertEqual(len(masked), len(f"token={SECRET} done"))


class StreamTest(PtyReelTestCase):
    """The stream filter sees a value split across two reads."""

    def test_split_across_chunks(self) -> None:
        """Holding a tail is what makes the second half match."""
        masker = StreamMasker(secret_forms([SECRET]))
        released = masker.feed("value=hunter2") + masker.feed("hunter2 end")
        released += masker.flush()
        self.assertNotIn(SECRET, released)
        self.assertIn("value=", released)
        self.assertIn(" end", released)

    def test_nothing_is_lost(self) -> None:
        """Everything fed comes out, masked or not."""
        masker = StreamMasker(secret_forms([SECRET]))
        released = masker.feed("hello ") + masker.feed("world") + masker.flush()
        self.assertEqual(released, "hello world")

    def test_no_secrets_passes_through(self) -> None:
        """With nothing to mask the filter adds no delay."""
        masker = StreamMasker(())
        self.assertEqual(masker.feed("abc"), "abc")
        self.assertEqual(masker.flush(), "")


class RecordingTest(PtyReelTestCase):
    """The screen pass catches what the stream pass cannot."""

    def test_value_wrapped_across_a_line(self) -> None:
        """A secret broken by the terminal's wrap is still redacted."""
        screen = TerminalScreen(cols=10, rows=3)
        screen.feed(f"x={SECRET}", time_ms=0)
        recording = mask_recording(screen.snapshot(), secret_forms([SECRET]))
        self.assertNotIn(SECRET, dump(recording).replace("\n", ""))
        self.assertIn("*", dump(recording))

    def test_value_rebuilt_by_a_redraw(self) -> None:
        """A secret assembled by a carriage return redraw is redacted."""
        screen = TerminalScreen(cols=40, rows=3)
        screen.feed("please wait", time_ms=0)
        screen.feed(f"\rtoken {SECRET}", time_ms=100)
        recording = mask_recording(screen.snapshot(), secret_forms([SECRET]))
        self.assertNotIn(SECRET, dump(recording))

    def test_cell_count_is_unchanged(self) -> None:
        """Masking rewrites characters, never the shape of the grid."""
        screen = TerminalScreen(cols=40, rows=3)
        screen.feed(f"token {SECRET}", time_ms=0)
        before = screen.snapshot()
        after = mask_recording(before, secret_forms([SECRET]))
        self.assertEqual(len(after.lines), len(before.lines))
        for original, masked in zip(before.lines, after.lines, strict=True):
            self.assertEqual(len(original.chars), len(masked.chars))
            self.assertEqual(original.times, masked.times)

    def test_no_forms_returns_the_same_object(self) -> None:
        """With nothing to mask there is nothing to rebuild."""
        screen = TerminalScreen(cols=8, rows=2)
        screen.feed("abc", time_ms=0)
        recording = screen.snapshot()
        self.assertIs(mask_recording(recording, ()), recording)


if __name__ == "__main__":
    unittest.main()
