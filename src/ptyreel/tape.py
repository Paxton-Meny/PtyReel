"""The tape data model.

This module declares what a tape is. It does not know how to read one, which
keeps the grammar in :mod:`ptyreel.parse` and leaves a single place to look up
what a setting means. Every value here has already been validated by the
parser, so the driver and the renderer consume these objects without
re-checking them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, TypeAlias

__all__ = [
    "DEFAULT_LOOP_DELAY_MS",
    "MAX_INSTRUCTIONS",
    "MAX_SCHEDULED_MS",
    "MAX_TAPE_BYTES",
    "MAX_TITLE_CHARS",
    "MAX_TYPE_CHARS",
    "SETTING_SPECS",
    "Instruction",
    "PressCtrl",
    "PressKey",
    "SetHidden",
    "SettingSpec",
    "SleepFor",
    "Tape",
    "TapeSettings",
    "TypeText",
]

MAX_TAPE_BYTES: Final[int] = 65_536
MAX_INSTRUCTIONS: Final[int] = 500
MAX_TYPE_CHARS: Final[int] = 1_000
MAX_SCHEDULED_MS: Final[int] = 120_000
MAX_TITLE_CHARS: Final[int] = 80
DEFAULT_LOOP_DELAY_MS: Final[int] = 2_500
BOOT_MS: Final[int] = 500


@dataclass(frozen=True, slots=True)
class TypeText:
    """Send characters one at a time, as a person typing would.

    Attributes
    ----------
    line : int
        One-based line in the tape this instruction came from.
    text : str
        Characters to send. Escapes are already resolved and no character
        below U+0020 survives except tab and newline.
    """

    line: int
    text: str


@dataclass(frozen=True, slots=True)
class PressKey:
    """Send the sequence for a named key.

    Attributes
    ----------
    line : int
        One-based line in the tape this instruction came from.
    key : str
        An upper case name present in :data:`ptyreel.keys.KEY_MAP`.
    """

    line: int
    key: str


@dataclass(frozen=True, slots=True)
class PressCtrl:
    """Send a control character.

    Attributes
    ----------
    line : int
        One-based line in the tape this instruction came from.
    letter : str
        A single ASCII letter. Case does not matter.
    """

    line: int
    letter: str


@dataclass(frozen=True, slots=True)
class SleepFor:
    """Hold the session still and keep reading output.

    Attributes
    ----------
    line : int
        One-based line in the tape this instruction came from.
    duration_ms : int
        How long the animation should dwell here.
    """

    line: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class SetHidden:
    """Stop or resume recording without stopping the session.

    Attributes
    ----------
    line : int
        One-based line in the tape this instruction came from.
    hidden : bool
        ``True`` for ``Hide``, ``False`` for ``Show``.
    """

    line: int
    hidden: bool


Instruction: TypeAlias = TypeText | PressKey | PressCtrl | SleepFor | SetHidden


@dataclass(frozen=True, slots=True, kw_only=True)
class SettingSpec:
    """How the parser should read one ``Set`` value.

    Attributes
    ----------
    field : str
        Name of the :class:`TapeSettings` field this setting fills.
    kind : str
        One of ``int``, ``duration``, ``bool``, ``text``, ``choice`` or
        ``theme``. The parser dispatches on this.
    minimum : int or None, optional
        Inclusive lower bound for ``int`` and ``duration`` kinds.
    maximum : int or None, optional
        Inclusive upper bound for ``int`` and ``duration`` kinds.
    choices : tuple of str or None, optional
        Accepted values for the ``choice`` kind.
    max_length : int or None, optional
        Longest accepted value for the ``text`` kind.
    """

    field: str
    kind: str
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] | None = None
    max_length: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TapeSettings:
    """Everything a tape can configure, with the defaults it inherits.

    Attributes
    ----------
    shell : str
        Shell to run. Only ``bash`` is supported.
    font_size : int
        Text size in pixels. Drives every other measurement.
    width : int
        Width of the whole image in pixels.
    height : int
        Height of the whole image in pixels.
    padding : int
        Gap between the window edge and the text, in pixels.
    typing_speed_ms : int
        Delay between typed characters.
    theme : str
        Name of a palette in :data:`ptyreel.theme.THEMES`.
    title : str
        Text shown in the title bar.
    loop : bool
        Whether the animation replays for ever.
    loop_delay_ms : int
        How long the finished session rests before a replay.
    mask_secrets : bool
        Whether values of secret-looking environment variables are redacted.
    anonymize : bool
        Whether the machine's identity is replaced with fixed stand-ins.
    """

    shell: str = "bash"
    font_size: int = 15
    width: int = 900
    height: int = 550
    padding: int = 24
    typing_speed_ms: int = 55
    theme: str = "github-dark"
    title: str = "bash"
    loop: bool = True
    loop_delay_ms: int = DEFAULT_LOOP_DELAY_MS
    mask_secrets: bool = True
    anonymize: bool = True


SETTING_SPECS: Final[dict[str, SettingSpec]] = {
    "Shell": SettingSpec(field="shell", kind="choice", choices=("bash",)),
    "FontSize": SettingSpec(field="font_size", kind="int", minimum=8, maximum=40),
    "Width": SettingSpec(field="width", kind="int", minimum=320, maximum=4096),
    "Height": SettingSpec(field="height", kind="int", minimum=200, maximum=4096),
    "Padding": SettingSpec(field="padding", kind="int", minimum=0, maximum=64),
    "TypingSpeed": SettingSpec(
        field="typing_speed_ms", kind="duration", minimum=1, maximum=2_000
    ),
    "Theme": SettingSpec(field="theme", kind="theme"),
    "Title": SettingSpec(field="title", kind="text", max_length=MAX_TITLE_CHARS),
    "Loop": SettingSpec(field="loop", kind="bool"),
    "LoopDelay": SettingSpec(
        field="loop_delay_ms", kind="duration", minimum=0, maximum=30_000
    ),
    "MaskSecrets": SettingSpec(field="mask_secrets", kind="bool"),
    "Anonymize": SettingSpec(field="anonymize", kind="bool"),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Tape:
    """A parsed, validated tape.

    Attributes
    ----------
    source : str
        Name used in error messages, normally the file name.
    output : str
        Workspace-relative path the SVG is written to.
    output_line : int
        Line the ``Output`` directive appeared on.
    requires : tuple
        Pairs of command name and the line that required it.
    settings : TapeSettings
        Resolved settings, defaults included.
    instructions : tuple
        Actions to perform, in order.
    """

    source: str
    output: str
    output_line: int
    requires: tuple[tuple[str, int], ...] = field(default=())
    settings: TapeSettings = field(default_factory=TapeSettings)
    instructions: tuple[Instruction, ...] = field(default=())

    def scheduled_ms(self) -> int:
        """Return how long the animation lasts by declared timing alone.

        Typing and sleeping are the only instructions that take time in the
        animation. Command output is placed at the instant the command was
        entered, so it adds nothing here. The result is the timeline length
        the renderer will use, which is what makes a render reproducible.

        The count opens with :data:`BOOT_MS`, a pause after the prompt
        appears and before the first character is typed. Without it the
        animation starts mid-thought.

        Returns
        -------
        int
            Milliseconds from the start of the session to the last event.
        """
        total = BOOT_MS
        for instruction in self.instructions:
            if isinstance(instruction, TypeText):
                total += len(instruction.text) * self.settings.typing_speed_ms
            elif isinstance(instruction, SleepFor):
                total += instruction.duration_ms
        return total
