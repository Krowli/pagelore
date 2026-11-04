---
slug: dev-panes-prototype
title: "The two-pane screen ships behind a flag, and the line editor stays the default"
kind: decision
created: 2026-09-20
updated: 2026-11-04
checked: 2026-11-04T15:26:26+00:00
sources:
  - evals/panes_keystrokes.py
  - src/pagelore/dev.py
  - src/pagelore/panes.py
  - tests/test_panes.py
---

## Cause

The console decision put a redrawn two-pane TUI in Rejected: a widget loop holds
raw mode for the whole session and needs a pty test that races, where the line
editor is pipe-drivable. But "a screen like the opencode one" kept being the ask,
and the project rule is that a feature ships with a number from evals or a
failing test — so the screen could be built, on two conditions: behind a flag,
and measured.

## Decision

`lore dev --panes` (and the internal `panes` command) is an opencode-shaped
screen (first built as a two-pane browser, reshaped in [[panes-opencode-screen]]):
an ask box, then a transcript of the commands run in-process through the same
`cli.main` the CLI runs, a `/` command picker, and `o` to open the top hit of the
last ranked `search`; `q` is back to the line editor. The line editor stays the
default and the bare-`lore` probe contract (usage, exit 0, never a terminal
surface) is untouched — the panes are reached only through `--panes` or the
`panes` command.

The review discipline carried over from the line editor: what a key decides is a
pure function on a `State` model — turns, field, cursor, history, picker, hits,
viewport offset — called directly by tests with no terminal. Only the draw loop
touches `curses`, and one pty test proves the raw screen draws and answers keys.
`curses` is POSIX and the screen needs a real terminal; where either is missing
`--panes` prints one line and falls back to the line editor, so a pipe driving
`lore dev --panes` still reads lines (tested).

Measured (`evals/panes_keystrokes.py`, `make eval-panes`): find + read one page
is `len(slug) + 7` fewer keystrokes than the CLI's `search` + `show` round trip
(`len(slug) + 10` on the first two-pane layout) — the slug is never typed again —
and costs zero processes where the CLI spawns two. Against this store's 30 pages
the first-layout figure was 1165 keystrokes. This does not
reverse the earlier rejection: that rejection set the *default*; the panes are
the opt-in answer to the screen request, invisible to anything that leans on the
plain contract. [[dev-console-stdlib-only]]
