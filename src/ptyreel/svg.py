"""Turning a recording into a self-contained animated SVG.

The document holds no script, no external reference and no embedded font. It
animates with CSS alone, which is what lets it play inside a README where
scripts never run.

Text is positioned rather than flowed. Every run of characters carries the
exact horizontal position of its first column and the exact width it must
occupy, so a reader whose machine has none of the preferred fonts still sees
columns line up instead of drifting further out of true with every character.

Three animations carry the session. Cells switch from hidden to shown at the
moment they were written. Line versions switch on at their birth and off when
something replaced them. The content group slides upward as the session
scrolls, and the cursor rides along with it. All of them share one cycle
length, so a looping document stays in step for ever rather than drifting
apart after the first pass.

Rendering is a pure function of its arguments. It reads no clock, draws no
random numbers and iterates no unordered collection, so the same recording
always produces the same bytes.
"""

from __future__ import annotations

from typing import Final

from ptyreel.chrome import footer, header
from ptyreel.errors import RenderError
from ptyreel.layout import FONT_STACK, Layout
from ptyreel.recording import NEVER, LineVersion, Recording, Style
from ptyreel.tape import TapeSettings
from ptyreel.theme import Theme, resolve_theme
from ptyreel.timeline import BUCKET_MS, Timeline, build_timeline
from ptyreel.xmltext import attrs, escape_text, sanitize

__all__ = ["MAX_RUNS", "render_svg"]

MAX_RUNS: Final[int] = 40_000
_BLINK_MS: Final[int] = 1_100


def render_svg(recording: Recording, *, settings: TapeSettings) -> str:
    """Render a captured session as an animated SVG document.

    Parameters
    ----------
    recording : Recording
        The captured session.
    settings : TapeSettings
        The tape's settings, which fix the size, the palette and whether the
        animation repeats.

    Returns
    -------
    str
        A complete document, ending in a single newline and containing no
        carriage return.

    Raises
    ------
    RenderError
        If the session needs more runs of text or more animations than the
        documented limits allow.
    ValueError
        If the settings describe an image too small to hold a grid.
    """
    layout = Layout.from_settings(settings)
    theme = resolve_theme(settings.theme)
    timeline = build_timeline(
        recording, loop=settings.loop, loop_delay_ms=settings.loop_delay_ms
    )
    title = sanitize(" ".join(settings.title.split()))

    body: list[str] = []
    body.append(
        "<svg"
        + attrs(
            xmlns="http://www.w3.org/2000/svg",
            viewBox=f"0 0 {layout.width} {layout.height}",
            width=layout.width,
            height=layout.height,
            preserveAspectRatio="xMidYMid meet",
            role="img",
        )
        + ">"
    )
    body.append(f"<title>{escape_text(title or 'Terminal session')}</title>")
    body.append("<style>")
    body.extend(_stylesheet(recording, layout, theme, timeline))
    body.append("</style>")
    body.extend(header(layout, theme, title=title))
    body.extend(_content(recording, layout, timeline))
    body.extend(footer(layout, theme))
    body.append("</svg>")
    return "\n".join(body) + "\n"


def _stylesheet(
    recording: Recording, layout: Layout, theme: Theme, timeline: Timeline
) -> list[str]:
    """Build every CSS rule the document needs."""
    cycle = f"{timeline.cycle_ms / 1000:.3f}s"
    repeat = "infinite" if timeline.loop else "1"
    fill = "none" if timeline.loop else "forwards"
    rules = [
        f"text{{font-family:{FONT_STACK};font-size:{layout.font_size}px;"
        f"fill:{theme.foreground};white-space:pre}}",
    ]
    animated = [
        selector
        for selector, present in ((".c", timeline.reveals), (".v", timeline.windows))
        if present
    ]
    if animated:
        rules.append(
            f"{','.join(animated)}{{opacity:0;animation-duration:{cycle};"
            f"animation-timing-function:step-end;animation-iteration-count:{repeat};"
            f"animation-fill-mode:{fill}}}"
        )
    rules.extend(_style_rules(recording, theme))
    for name, bucket in timeline.reveals:
        stop = timeline.percent(bucket * BUCKET_MS)
        rules.append(f".{name}{{animation-name:{name}}}")
        rules.append(f"@keyframes {name}{{0%{{opacity:0}}{stop}%{{opacity:1}}}}")
    for name, birth, death in timeline.windows:
        rules.append(f".{name}{{animation-name:{name}}}")
        rules.append(f"@keyframes {name}{{{_window_stops(timeline, birth, death)}}}")
    rules.extend(_scroll_rules(recording, layout, timeline, cycle, repeat, fill))
    rules.extend(_cursor_rules(recording, layout, theme, timeline, cycle, repeat, fill))
    still = "*{animation:none!important}"
    if timeline.reveals:
        still += ".c{opacity:1}"
    rules.append(f"@media(prefers-reduced-motion:reduce){{{still}}}")
    return rules


def _window_stops(timeline: Timeline, birth: int, death: int) -> str:
    """Build the keyframe stops for one line version's lifetime."""
    born = timeline.percent(birth * BUCKET_MS)
    if death == NEVER:
        if birth == 0:
            return "0%{opacity:1}"
        return f"0%{{opacity:0}}{born}%{{opacity:1}}"
    died = timeline.percent(death * BUCKET_MS)
    if birth == 0:
        return f"0%{{opacity:1}}{died}%{{opacity:0}}"
    return f"0%{{opacity:0}}{born}%{{opacity:1}}{died}%{{opacity:0}}"


def _style_rules(recording: Recording, theme: Theme) -> list[str]:
    """Build one rule per distinct text style in the recording."""
    rules: list[str] = []
    for index, style in enumerate(recording.styles):
        if index == 0:
            continue
        declarations = _declarations(style, theme)
        if declarations:
            rules.append(f".s{index}{{{declarations}}}")
    return rules


def _declarations(style: Style, theme: Theme) -> str:
    """Build the declarations for one text style."""
    parts: list[str] = []
    if style.fg is not None:
        parts.append(f"fill:{theme.ansi[style.fg]}")
    elif style.dim:
        parts.append(f"fill:{theme.dim}")
    if style.dim and style.fg is not None:
        parts.append("opacity:0.65")
    if style.bold:
        parts.append("font-weight:700")
    if style.italic:
        parts.append("font-style:italic")
    if style.underline:
        parts.append("text-decoration:underline")
    return ";".join(parts)


def _scroll_rules(
    recording: Recording,
    layout: Layout,
    timeline: Timeline,
    cycle: str,
    repeat: str,
    fill: str,
) -> list[str]:
    """Build the animation that slides content upward as the session scrolls."""
    if len(recording.scrolls) < 2:
        return []
    stops: list[str] = []
    for time_ms, top in recording.scrolls:
        offset = -top * layout.line_height
        stops.append(f"{timeline.percent(time_ms)}%{{transform:translateY({offset}px)}}")
    return [
        f"#scroll{{animation:scroll {cycle} step-end {repeat};animation-fill-mode:{fill}}}",
        f"@keyframes scroll{{{''.join(stops)}}}",
    ]


def _cursor_rules(
    recording: Recording,
    layout: Layout,
    theme: Theme,
    timeline: Timeline,
    cycle: str,
    repeat: str,
    fill: str,
) -> list[str]:
    """Build the cursor's blink and, when it moves, its path."""
    blink = (
        f"@keyframes blink{{0%,55%{{opacity:1}}56%,100%{{opacity:0}}}}"
    )
    if len(recording.cursors) < 2:
        return [
            f"#cursor{{fill:{theme.cursor};animation:blink "
            f"{_BLINK_MS / 1000:.3f}s step-end infinite}}",
            blink,
        ]
    stops: list[str] = []
    for time_ms, line, column in recording.cursors:
        x = layout.column_x(column)
        y = layout.baseline(line) - layout.cursor_offset
        stops.append(
            f"{timeline.percent(time_ms)}%{{transform:translate({x}px,{y}px)}}"
        )
    return [
        f"#cursor{{fill:{theme.cursor};animation:track {cycle} step-end {repeat},"
        f"blink {_BLINK_MS / 1000:.3f}s step-end infinite;"
        f"animation-fill-mode:{fill},none}}",
        f"@keyframes track{{{''.join(stops)}}}",
        blink,
    ]


def _content(recording: Recording, layout: Layout, timeline: Timeline) -> list[str]:
    """Build the scrolling group holding every line and the cursor."""
    final_top = recording.scrolls[-1][1]
    group = attrs(
        id="scroll",
        transform=f"translate({layout.content_x},{layout.content_top}) "
        f"translate(0,{-final_top * layout.line_height})",
    )
    lines = [f"<g{group} xml:space=\"preserve\">"]
    runs = 0
    for version in recording.lines:
        markup, count = _line(version, layout, timeline)
        runs += count
        if runs > MAX_RUNS:
            raise RenderError(
                f"session needs more than {MAX_RUNS} runs of text, "
                "record a shorter session"
            )
        if markup:
            lines.append(markup)
    lines.append(_cursor(recording, layout))
    lines.append("</g>")
    return lines


def _line(
    version: LineVersion, layout: Layout, timeline: Timeline
) -> tuple[str, int]:
    """Build one line version's text element, and count the runs in it."""
    spans: list[str] = []
    count = 0
    for start, stop, style_id, bucket in _runs(version):
        text = version.chars[start:stop]
        reveal = timeline.reveal_class(bucket * BUCKET_MS)
        classes = " ".join(
            part
            for part in (
                f"s{style_id}" if style_id else "",
                f"c {reveal}" if reveal else "",
            )
            if part
        )
        marks = attrs(x=layout.column_x(start), textLength=(stop - start) * layout.char_width)
        if classes:
            marks += attrs(class_=classes)
        spans.append(
            f'<tspan{marks} lengthAdjust="spacingAndGlyphs">{escape_text(text)}</tspan>'
        )
        count += 1
    if not spans:
        return "", 0
    window = timeline.window_class(version.birth_ms, version.death_ms)
    marks = attrs(x=0, y=layout.baseline(version.line))
    if window:
        marks += attrs(class_=f"v {window}")
    return f"<text{marks}>{''.join(spans)}</text>", count


def _runs(version: LineVersion) -> list[tuple[int, int, int, int]]:
    """Split a line into runs sharing a style and a reveal bucket."""
    runs: list[tuple[int, int, int, int]] = []
    start = -1
    style_id = 0
    bucket = 0
    for column, stamp in enumerate(version.times):
        if stamp == NEVER:
            if start >= 0:
                runs.append((start, column, style_id, bucket))
                start = -1
            continue
        cell_style = version.styles[column]
        cell_bucket = stamp // BUCKET_MS
        if start >= 0 and cell_style == style_id and cell_bucket == bucket:
            continue
        if start >= 0:
            runs.append((start, column, style_id, bucket))
        start = column
        style_id = cell_style
        bucket = cell_bucket
    if start >= 0:
        runs.append((start, len(version.times), style_id, bucket))
    return runs


def _cursor(recording: Recording, layout: Layout) -> str:
    """Build the cursor block at its final resting place."""
    _, line, column = recording.cursors[-1]
    marks = attrs(
        id="cursor",
        x=0,
        y=0,
        width=layout.cursor_width,
        height=layout.cursor_height,
        rx=1.5,
        transform=f"translate({layout.column_x(column)},"
        f"{layout.baseline(line) - layout.cursor_offset})",
    )
    return f"<rect{marks}/>"
