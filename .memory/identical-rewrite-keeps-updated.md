---
slug: identical-rewrite-keeps-updated
title: "Identical rewrite must not bump updated"
kind: bug
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/stats.py
  - src/pagelore/write.py
---

## Cause

`write_page` always rendered the page with today's date and always called
`atomic_write`, even when the resulting text was byte-for-byte identical to
what was already on disk. A later staleness check (task 4 of this plan) marks
a page stale when its `sources` changed in git after the page's own last
commit — so a no-op re-run that bumped `updated` would falsely "refresh" a
page nobody actually touched, hiding real staleness behind a fake edit.

## Fix

Inside `write_page`'s existing per-page lock (`write.py`, the
`UNLOCKED_RETRIES` loop), the candidate page is now rendered twice: once with
the *prior* `updated` value (`meta.get("updated", today)`), compared
byte-for-byte against the file as read under that same lock. Only if they
differ does `updated` get set to `today` and `atomic_write` run. The skip
returns early regardless of `lock.held` — since nothing was written, there is
nothing for the unlocked-retry recheck to verify, so this does not interact
with that retry logic.

`write.main()` learns about this through a module-level flag, `last_unchanged`
(`write.py` ~315, reset to `False` at the top of every `write_page()` call and
set to `True` only at the byte-identical skip-return inside the lock) — the
same idiom `search.py` already uses for `last_path`/`last_touching`.
`write_page`'s signature and return type stay untouched (a bare `Path`), so its
~15 existing call sites (tests, `evals/run.py`) needed no changes. `main()`
reads `last_unchanged` once, right after `write_page()` returns (~write.py 653),
and never re-derives the answer itself. On a match it prints `unchanged:
nothing to write` to stderr instead of `replaced:`/`appended:` lines, still
exits 0, still prints the path, and logs `mode="unchanged"` instead of
`"create"`/`"merge"`. `stats.summarise` counts it in a new `unchanged` field,
shown next to `new`/`merged` in the `writes` line.

## Rejected alternative

Returning `(path, changed)` from `write_page` was simpler in isolation but
would have required touching every caller (`tests/test_merge.py`,
`tests/test_concurrency.py`, `tests/test_retrieval_quality.py`,
`evals/run.py`, ...) that currently unpacks its return as a single `Path`.

A version of `main()` that instead read the file itself, before and after
calling `write_page()`, and compared those two snapshots to decide `unchanged`
for reporting, was built and then removed in review. Two problems: it read the
file with a strict `path.read_text(encoding="utf-8")`, which is *not* the
tolerant read (`errors="replace"`) every other page read in this project goes
through — one non-UTF-8 byte already sitting in an existing page (e.g. from a
bad paste) made that read raise `UnicodeDecodeError` and crash `lore write`
outright on a page HEAD wrote fine before this feature existed. And it was a
second, unsynchronized read pair racing `write_page`'s own byte-for-byte
comparison, which is done once, inside the per-page lock, against the file as
read under that same lock — under a concurrent writer landing between
`main()`'s own before and after reads, a call `write_page()` genuinely skipped
could still be reported as a merge, or vice versa. The module flag replaces
both reads with a fact `write_page()` already decided once, correctly
synchronized, instead of `main()` rediscovering it a second time and getting
it wrong.
