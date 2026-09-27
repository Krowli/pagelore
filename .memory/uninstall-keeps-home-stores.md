---
slug: uninstall-keeps-home-stores
title: "uninstall --yes removes only pagelore's own files, never a --store home store"
kind: bug
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/uninstall.py
  - tests/test_init.py
  - docs/installation.md
---

## Cause

`lore uninstall --yes` ran `shutil.rmtree` on the whole home directory
(`~/.pagelore`, or `$PAGELORE_HOME`). That directory is not only program state:
`lore init --store home` puts a project's store at `<home>/<project>/` and links the
project's `.memory` to it. So `--yes` deleted every such project's pages, while its
help text said "the block, not your pages". Nothing tested `--yes` with a home store.

## Decision

Uninstall deletes by allow-list, not by directory. The program's own files in the
home are enumerated from the code that writes them: `instructions.BLOCK`
(`AGENT.md`), `instructions.STAMP` (`.version`), and the `.<name>.<pid>.<tid>.tmp`
scratch files `lib.atomic_write` leaves if it dies mid-write. Everything else is
kept. Stores are recognised by the library's own test (`lib.page_paths` non-empty,
or a `.log.jsonl`), only to label them in the output — an unrecognised entry is kept
too, never guessed at. The home directory is removed only when it is empty after
that; otherwise uninstall lists what it kept and prints the `rm -r` to delete it by
hand.

The `~/.project-memory` link from the 0.6.0 rename is removed only when it resolves
to the current home *and* the home is gone: a pre-0.6.0 `--store home` project
reaches its kept pages through that link, so removing it while the store stays
would silently darken the store.

## Rejected

Excluding stores by name, or deleting anything that "looks like" program state —
the ownership rule is: if the program did not write it, it does not delete it.
