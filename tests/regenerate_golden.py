"""Rewrite the stored documents the renderer is compared against.

Run this after a deliberate change to the renderer, read the diff, and commit
the result with the change that caused it.

    python tests/regenerate_golden.py

The file name does not match the discovery pattern, so the gate never runs it.
"""

from __future__ import annotations

import sys

from support import GOLDEN_DIR

from fixtures import RECORDINGS, SETTINGS

from ptyreel.svg import render_svg


def main() -> int:
    """Render every fixture and write it to the golden directory.

    Returns
    -------
    int
        Always zero. Failures raise instead.
    """
    GOLDEN_DIR.mkdir(exist_ok=True)
    for name in sorted(RECORDINGS):
        document = render_svg(RECORDINGS[name], settings=SETTINGS[name])
        path = GOLDEN_DIR / f"{name}.svg"
        before = path.read_bytes().decode("utf-8") if path.exists() else None
        path.write_text(document, encoding="utf-8", newline="\n")
        state = "unchanged" if before == document else "changed"
        print(f"{state:>9}  {path.name}  {len(document)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
