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

The hooks run exactly the gate above. They report and never change a file.

Tests that drive a pseudo-terminal skip themselves off POSIX, so a Windows
machine runs most of the suite but not all of it. Run the gate under WSL before
pushing.

## Test layout

`tests/support.py` puts `src` on the import path and holds the shared
assertions. Every test module imports it before it imports anything from
`ptyreel`. Two files are deliberately outside the discovery pattern and are
never collected: `tests/fixtures.py`, which defines the recordings the renderer
is tested against, and `tests/regenerate_golden.py`.

`tests/test_standards.py` stands in for the linter and the type checker the
gate does not have. It asserts the docstrings, the annotations, the absence of
comments in the package, and the module shape.

## Which platforms run what

The gate runs on Linux and on macOS. The pseudo-terminal driver is where they
differ in ways that matter: macOS ships bash 3.2, and a terminal whose child
has exited reports end of file there while Linux reports an error instead.
Both are handled, and the matrix is what keeps them handled.

The action's self-test runs on Linux only. It asserts that a freshly rendered
demo matches the committed one, and the committed one was rendered on Linux, so
that check cannot be platform independent. It tests the action, not the shell.

## Regenerating golden files

The renderer is compared against stored documents in `tests/golden/`. After a
deliberate change to the renderer:

```bash
python tests/regenerate_golden.py
```

Read the diff, then commit the goldens in the same commit as the change that
caused them.

## Rendering the demos

`demos/out/` holds rendered output that the README links to. Refresh it by
hand and commit the result:

```bash
python -m ptyreel demos/hello.tape demos/colors.tape demos/check.tape
```

Continuous integration never renders and never pushes. Rendering runs the
commands in a tape, so a person decides when that happens.

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
- Every release must also move the major-version tag, because that is what
  the README tells consumers to pin. Forgetting it leaves them on the previous
  release with no sign anything is wrong:

  ```bash
  git tag -f -a v0 -m "Moving tag for the 0.x series, currently 0.2.0"
  git push --force origin v0
  ```

- Refresh the rendered demos by hand and commit them with the change that
  altered them. Continuous integration checks that `demos/out/hello.svg` and
  `demos/out/check.svg` match a fresh render, so a stale image fails the build.
  `demos/out/colors.svg` is excluded because it lists a real directory, so its
  output differs from one machine to the next.
