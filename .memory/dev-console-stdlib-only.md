---
slug: dev-console-stdlib-only
title: "The console is a line editor on stdlib, gated by a tty"
kind: decision
created: 2026-09-20
updated: 2026-09-20
checked: 2026-11-04T15:26:26+00:00
sources:
  - src/pagelore/dev.py
  - src/pagelore/cli.py
  - tests/test_dev.py
  - README.md
---

## Cause

Management and testing wanted a surface like the opencode one — a full screen
with a field, labels and commands inside, and a place to try commands against a
store that does not matter. Two constraints shaped what that could be. The
package is deliberately stdlib-only (`dependencies = []`, Python 3.9+) and a
redrawn widget needs raw mode plus a pty test that races, the discipline already
paid for in `menu.py` but not for a whole console.

## Decision

`lore dev` is a line editor, not a menu: `input()` plus the `readline` module
where Python ships it, chrome printed between commands rather than redrawn.
Every line runs as a real child process (`$PYTHON -m pagelore <line>`) from the
current directory, so output, exit codes and `FIX:` lines are exactly what an
agent would see — that fidelity is the point, because the slow part of trying a
build used to be installing it.

`--sandbox` points every child at a throwaway store, project, cwd and HOME, and
discards all of it on exit, so `write`, `init` and `uninstall` can be rehearsed
against nothing that matters. Sandbox children get their own fake HOME; the
console's own environment is never the vector.

A bare `lore` opens the console only when stdin and stdout are a real terminal.
An agent, a script or a CI job — where a probe must read exit 0 and usage text —
never sees a terminal here, so they keep the plain path. Both faces of the
program are one `main()`: the gate is `isatty()`, the same split the wizard's
`menu.py` already draws.

## Rejected

**A redrawn two-pane TUI with a live widget loop.** It needs raw mode held for
the whole session, which is where `menu.py`'s keyboard menu already had to learn
its hardest lesson, and a test that races keypresses. The printed-chrome REPL
gets the same surface for a test that can just pipe lines.

**Auto-opening on a non-terminal.** A bare `lore` printing usage and exiting 0
is the probe contract `evals/acceptance.py` and the install smoke lean on.

**A dependency on textual or prompt_toolkit.** It would end the stdlib-only
bet that made the Wheel tiny and the floor 3.9.
