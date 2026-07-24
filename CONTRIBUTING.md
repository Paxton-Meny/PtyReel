# Contributing

This is a personal project. External pull requests are not accepted; issues
are welcome and are the supported channel for bugs and feature ideas.

## Filing an issue

Use the bug report or feature request template. A good bug report carries a
minimal tape file, the exact command, expected versus actual output, and the
Python version.

## Security

Do not open a public issue for a suspected vulnerability. See
[SECURITY.md](SECURITY.md) for private reporting.

## Working with the code locally

Requirements: Python 3.11+ on a POSIX system (Linux, macOS, or WSL). There is
nothing to install; the project is standard-library only, tests included.

Run the quality gate:

```bash
python -m compileall -q src tests && python -m unittest discover -s tests
```

Enable the committed git hooks once per clone:

```bash
git config core.hooksPath hooks
```

## Maintainer conventions

Documented so the history stays legible.

- Branch from `main`, never commit to it directly. Branches are
  `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `perf/<slug>`,
  `refactor/<slug>`, or `research/<slug>`.
- Atomic commits: imperative subject of 72 characters or fewer, body
  explaining why when the subject alone cannot.
- Rebase-merge keeps `main` linear while preserving each branch's commits;
  squash only when a branch's commits are not individually meaningful.
- Releases get annotated semver tags on `main` after the release PR merges,
  with the changelog updated in the same branch as the change it records.
