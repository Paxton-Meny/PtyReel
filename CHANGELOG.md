# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
