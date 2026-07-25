"""The window the terminal text is drawn inside.

This module knows about shape and never about content. It is handed a layout
and a palette and returns the markup that goes before the text and the markup
that goes after it, so the renderer stays a matter of assembling three pieces
in order.

The frame is a rounded panel over a soft gradient, lifted by two overlapping
shadows: a wide, faint one for depth and a tight, darker one for contact. One
shadow looks flat, and a single large blur looks like a smudge. Two thin
strokes finish the edge, a dark one that separates the panel from the
background and a barely visible light one just outside it, which is what stops
the corner from looking cut out.
"""

from __future__ import annotations

from ptyreel.layout import FONT_STACK, Layout
from ptyreel.theme import Theme
from ptyreel.xmltext import attrs, escape_text

__all__ = ["footer", "header"]


def header(layout: Layout, theme: Theme, *, title: str) -> list[str]:
    """Return the markup that opens the window.

    Parameters
    ----------
    layout : Layout
        Resolved geometry.
    theme : Theme
        Validated palette.
    title : str
        Text for the title bar. Already sanitised by the caller.

    Returns
    -------
    list of str
        One string per output line, ending inside the clipped content group
        so text can be appended directly.
    """
    scale = layout.window_width / 780
    wide_blur = max(4.0, 20 * scale)
    wide_drop = max(4.0, 18 * scale)
    tight_blur = max(1.0, 5 * scale)
    tight_drop = max(1.0, 4 * scale)
    title_size = max(8, round(layout.font_size * 0.85))
    centre_x = layout.window_x + layout.window_width / 2
    title_baseline = layout.light_y + round(title_size * 0.36)
    divider = layout.window_y + layout.title_bar_height + 0.5

    backdrop_marks = attrs(
        x=0,
        y=0,
        width=layout.width,
        height=layout.height,
        rx=layout.backdrop_radius,
        ry=layout.backdrop_radius,
        fill="url(#backdrop)",
    )
    bar_marks = attrs(
        x=layout.window_x,
        y=layout.window_y,
        width=layout.window_width,
        height=layout.title_bar_height,
        fill=theme.surface,
    )
    divider_marks = attrs(
        x1=layout.window_x,
        y1=divider,
        x2=layout.window_x + layout.window_width,
        y2=divider,
        stroke=theme.border,
        stroke_opacity="0.8",
        stroke_width=1,
    )
    lines = [
        "<defs>",
        f'<linearGradient id="backdrop"{attrs(x1=0, y1=0, x2=1, y2=1)}>',
        f'<stop{attrs(offset=0, stop_color=theme.backdrop_from, stop_opacity="0.16")}/>',
        f'<stop{attrs(offset=1, stop_color=theme.backdrop_to, stop_opacity="0.09")}/>',
        "</linearGradient>",
        f'<filter id="lift"{attrs(x="-12%", y="-10%", width="124%", height="130%")}'
        ' color-interpolation-filters="sRGB">',
        f'<feGaussianBlur{attrs(in_="SourceAlpha", stdDeviation=wide_blur, result="wb")}/>',
        f'<feOffset{attrs(in_="wb", dy=wide_drop, result="wo")}/>',
        f'<feFlood{attrs(flood_color=theme.shadow, flood_opacity="0.42", result="wf")}/>',
        f'<feComposite{attrs(in_="wf", in2="wo", operator="in", result="ws")}/>',
        f'<feGaussianBlur{attrs(in_="SourceAlpha", stdDeviation=tight_blur, result="tb")}/>',
        f'<feOffset{attrs(in_="tb", dy=tight_drop, result="to")}/>',
        f'<feFlood{attrs(flood_color=theme.shadow, flood_opacity="0.30", result="tf")}/>',
        f'<feComposite{attrs(in_="tf", in2="to", operator="in", result="ts")}/>',
        "<feMerge>",
        '<feMergeNode in="ws"/><feMergeNode in="ts"/><feMergeNode in="SourceGraphic"/>',
        "</feMerge>",
        "</filter>",
        '<clipPath id="window-clip">',
        f"<rect{_window_rect(layout)}/>",
        "</clipPath>",
        '<clipPath id="content-clip">',
        f"<rect{_content_rect(layout)}/>",
        "</clipPath>",
        "</defs>",
        f"<rect{backdrop_marks}/>",
        '<g filter="url(#lift)">',
        f"<rect{_window_rect(layout)}{attrs(fill=theme.background)}/>",
        '<g clip-path="url(#window-clip)">',
        f"<rect{bar_marks}/>",
        f"<line{divider_marks}/>",
    ]
    for index, colour in enumerate(theme.traffic_lights):
        light_marks = attrs(
            cx=layout.light_x + index * layout.light_gap,
            cy=layout.light_y,
            r=layout.light_radius,
            fill=colour,
            stroke="#000000",
            stroke_opacity="0.12",
        )
        lines.append(f"<circle{light_marks}/>")
    if title:
        title_marks = attrs(
            x=centre_x,
            y=title_baseline,
            text_anchor="middle",
            font_family=FONT_STACK,
            font_size=title_size,
            letter_spacing="0.2",
            fill=theme.dim,
        )
        lines.append(f"<text{title_marks}>{escape_text(title)}</text>")
    lines.append('<g clip-path="url(#content-clip)">')
    return lines


def footer(layout: Layout, theme: Theme) -> list[str]:
    """Return the markup that closes the window.

    Parameters
    ----------
    layout : Layout
        Resolved geometry.
    theme : Theme
        Validated palette.

    Returns
    -------
    list of str
        One string per output line, closing everything :func:`header`
        opened and drawing the two edge strokes.
    """
    inner = attrs(
        x=layout.window_x + 0.5,
        y=layout.window_y + 0.5,
        width=layout.window_width - 1,
        height=layout.window_height - 1,
        rx=layout.window_radius - 0.5,
        ry=layout.window_radius - 0.5,
        fill="none",
        stroke=theme.border,
        stroke_width=1,
    )
    outer = attrs(
        x=layout.window_x - 0.5,
        y=layout.window_y - 0.5,
        width=layout.window_width + 1,
        height=layout.window_height + 1,
        rx=layout.window_radius + 0.5,
        ry=layout.window_radius + 0.5,
        fill="none",
        stroke="#ffffff",
        stroke_opacity="0.04",
        stroke_width=1,
    )
    return ["</g>", "</g>", f"<rect{inner}/>", f"<rect{outer}/>", "</g>"]


def _window_rect(layout: Layout) -> str:
    """Return the attributes of the window panel."""
    return attrs(
        x=layout.window_x,
        y=layout.window_y,
        width=layout.window_width,
        height=layout.window_height,
        rx=layout.window_radius,
        ry=layout.window_radius,
    )


def _content_rect(layout: Layout) -> str:
    """Return the attributes of the region text is clipped to."""
    top = layout.window_y + layout.title_bar_height
    return attrs(
        x=layout.window_x,
        y=top,
        width=layout.window_width,
        height=layout.window_y + layout.window_height - top,
    )
