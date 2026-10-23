# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-10-23

### Added

- Releases are published to PyPI as `ptyreel`.
- A `ptyreel-check` hook for [pre-commit](https://pre-commit.com) validates
  every staged `.tape` file without running it.

## [0.2.0] - 2026-10-11

### Added

- Sessions are recorded as a generic machine by default. `$USER`, `$HOME` and
  `~` read as `LocalUser` and `/home/LocalUser`, and what `whoami`, `id` and
  `hostname` print is substituted on the way out, since those ask the kernel
  and no environment variable reaches them. Each session also runs with a fresh
  home directory of its own, so a tape cannot write into your real one. Turn it
  off with `Set Anonymize false`.
- `demos/scroll.tape`, a demo whose output is taller than the window. The
  action self-test re-renders it and compares, so the scrolling path always
  has an up to date image behind it.

### Changed

- Secret redaction and identity substitution now share one streaming rewriter
  rather than each holding their own copy of the tail-buffering logic.
- Every rendered document differs from 0.1.0 in its markup, including ones
  that look the same. A workflow that compares a committed image against a
  fresh render needs the image rendered again.

### Fixed

- A session whose output outgrew the window was misplaced in every browser.
  For the whole animation the text sat shifted left by the padding and up by
  the title bar, clipped at the window's left edge. The scroll animation's CSS
  transform replaced the content's position instead of adding to it. Renderers
  that ignore animation drew the final frame correctly, which is how it went
  unnoticed.
- Once a session scrolled, the line just above the first row stayed visible
  in the window's top padding. Only the terminal's rows are shown now.
- When output overflowed the window, the new lines appeared below the last
  row, in the bottom padding, a moment before the scroll that made room for
  them. Text and scrolling now change on the same moments.
- A document set to `Set Loop false` went blank in a browser the moment it
  finished playing.
- A reader who asked for reduced motion saw only the lines that existed when
  the session started, which is usually none of them.
- Dim text with a colour played at full strength in a browser. It was dimmed
  only where animation is ignored.

## [0.1.0] - 2026-07-25

First tagged release. The tape format and the rendered output may still change
in any 0.x release.

### Added

- Tape format: `Output`, `Require`, eleven `Set` keys, `Type`, named keys,
  `Ctrl+<letter>`, `Sleep`, and `Hide` and `Show`. Every tape is validated
  before a pseudo-terminal opens, and every error names the file and the line.
- Terminal model covering text, tabs, backspace, carriage return, newline,
  cursor movement, erasing, scrolling, and colour and text attributes. A
  rewritten line is replaced rather than drawn over, so progress output and
  prompt redraws render correctly.
- Pseudo-terminal driver that runs a tape against a real shell in a fixed,
  short environment, with bounds on wall clock, output volume and screen size.
- Renderer producing a self-contained animated SVG. Animation is CSS only, so
  it plays where scripts do not run. Text runs carry an explicit position and
  width, so columns line up whichever monospace font a reader has.
- Reproducible output. The animation timeline comes from the tape's declared
  timing, so the same tape run twice produces the same bytes.
- Secret redaction for values of secret-looking environment variables, applied
  to the output stream and again to the finished screen.
- Output containment: paths are validated as strings, then walked through open
  descriptors that refuse to follow a symbolic link, then written atomically.
- `python -m ptyreel` with `--workspace`, `--output`, `--check` and `--version`.
- Composite action with `tape`, `output`, `check` and `workspace` inputs and an
  `svg-path` output.
- Two palettes, `github-dark` and `github-light`.
- Continuous integration running the quality gate, and local hooks that run the
  same one command.
- Demo tapes and their rendered output.
- Contributing guide, security policy, and issue and pull request templates.

[Unreleased]: https://github.com/Paxton-Meny/PtyReel/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Paxton-Meny/PtyReel/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Paxton-Meny/PtyReel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Paxton-Meny/PtyReel/releases/tag/v0.1.0
