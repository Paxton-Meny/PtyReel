# Security Policy

## Supported versions

Pre-1.0: only `main` and the latest tagged release receive security fixes.

## Reporting a vulnerability

Do not open a public issue. Submit a private security advisory through the
repository's Security tab. Include a description, a minimal reproduction
(ideally a tape file), and affected versions if known. Expect an
acknowledgement within 7 days and a remediation plan within 30.

## Scope

A tape file is code: playing one executes its commands in a real shell with
the invoking user's privileges. Tapes carry the same trust as the workflow or
user that runs them, so "a tape can run commands" is by design and out of
scope. In scope, and prioritized:

- Rendered SVG output escaping: terminal output that breaks out of the SVG
  document as markup or script.
- Output path containment: an `Output` directive writing outside the
  workspace via absolute paths, `..`, or symlinks.
- Secret exposure the renderer fails to mask when masking is configured.
- Resource exhaustion: a tape that hangs or unboundedly grows a run instead
  of failing fast.

There are no third-party dependencies; vulnerabilities in CPython itself
belong upstream.
