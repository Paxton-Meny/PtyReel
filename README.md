# PtyReel

Record scripted terminal sessions as self-contained animated SVGs, using only
the Python standard library.

You write a `.tape` file describing a session (type this, wait, press that).
PtyReel plays it inside a real pseudo-terminal, captures the output with its
timing and colors, and renders an animated SVG you can drop straight into a
README or docs site. No browser, no GIF encoder, no dependencies: a consumer
adds the action or runs the module, and gets living documentation of their
actual CLI.

## Status

Early development. The tape format and rendering output are not yet stable,
and the action interface does not exist yet. Nothing here is ready to depend
on.

## Planned shape

```
action.yml          the GitHub Action interface
src/ptyreel/        tape parsing, PTY capture, SVG rendering
tests/              unittest suite mirroring src/
demos/              .tape sources for this project's own examples
```

Runtime is POSIX-only by design (`pty` does not exist on Windows); the target
environment is a Linux CI runner or any Unix shell.

## License

Apache-2.0.
