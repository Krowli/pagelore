---
slug: panes-argparse-systemexit-crash
title: "Argparse SystemExit killed the panes screen; it is now the turn's rc"
kind: bug
created: 2026-09-21
updated: 2026-09-21
checked: 2026-11-04T15:26:26+00:00
sources:
  - src/pagelore/panes.py
  - tests/test_panes.py
---

## Cause

The panes field runs commands in-process through `cli.main`, where the REPL
runs them as children. Argparse validation (`search` with no query, `rm`
without a slug, `--version`, `--help`) does not return — it raises
`SystemExit`. In a child that is just the exit code; in-process it escaped
`run_command` and the curses loop (run_guarded catches only `curses.error`)
and took the whole screen down: picking `search` from the picker and pressing
Enter with no query threw the user out of the program entirely.

## Fix

`run_command` catches `SystemExit` around `cli.main` and turns it into the
turn's rc (`exc.code` when it is an int, else 1) — the same code a real child
would exit with, so the fidelity claim holds.

A bare `search` (no query, no flags) no longer reaches argparse at all: since
later screen work it is intercepted in `submit`, which leaves the field as
`lore > search ` and runs nothing, so the usage screen is unreachable from the
field except by the rarest flag-only invocation (a lone `-k`), which still
rides the SystemExit path into a red `exit 2` turn.

## Tests

`test_run_command_turns_argparse_exits_into_rcs` (rc 2 for a query-less
search, rc 0 for `search --version`) covers the guard directly; the screen
alive claim lives in `test_submit_of_a_bare_search_waits_for_the_query`.
Also caught there: a card test asserted a hardcoded `2026-09-20`, which broke
the day the store started dating pages the 21st — the assertion now matches a
`[score] YYYY-MM-DD` pattern instead.
