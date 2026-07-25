"""The ``python -m ptyreel`` command line.

Argument parsing lives here and nowhere else. Every path this module takes
ends in one of two calls into :mod:`ptyreel.pipeline`, so the behaviour of the
tool and the behaviour of the library cannot drift apart.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ptyreel import __version__
from ptyreel.errors import PtyReelError
from ptyreel.pipeline import check_tape, render_tape

__all__ = ["build_parser", "cli", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns
    -------
    argparse.ArgumentParser
        A parser accepting one or more tapes and the options that apply to
        them.
    """
    parser = argparse.ArgumentParser(
        prog="ptyreel",
        description="Record scripted terminal sessions as animated SVGs.",
    )
    parser.add_argument("tapes", nargs="+", metavar="TAPE", help="tape files to play")
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="DIR",
        help="directory every path must stay inside, default the current directory",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="write here instead of the tape's Output path, one tape only",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate without running anything or writing anything",
    )
    parser.add_argument("--version", action="version", version=f"ptyreel {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line and return an exit code.

    Parameters
    ----------
    argv : sequence of str or None, optional
        Arguments to parse. Defaults to the process arguments.

    Returns
    -------
    int
        Zero on success, one for any reported error, and 130 when
        interrupted.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.output is not None and len(args.tapes) > 1:
        parser.error("--output takes a single tape")
    workspace = Path.cwd() if args.workspace is None else Path(args.workspace)
    try:
        for tape in args.tapes:
            if args.check:
                check_tape(workspace, tape, output_override=args.output)
            else:
                written = render_tape(workspace, tape, output_override=args.output)
                print(written)
    except PtyReelError as exc:
        print(f"ptyreel: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ptyreel: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


def cli() -> None:
    """Entry point that exits with the code :func:`main` returns."""
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
