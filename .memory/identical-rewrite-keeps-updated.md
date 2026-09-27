---
slug: identical-rewrite-keeps-updated
title: "Identical rewrite must not bump updated"
kind: bug
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/write.py
  - src/pagelore/stats.py
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

`write.main()` learns about this after the fact for reporting purposes only,
by comparing the file's content before and after the call to `write_page`
(a separate read, not a return value — `write_page`'s signature deliberately
did not change, since it has ~15 call sites across tests and `evals/run.py`
that all treat its return as a bare `Path`). On a match it prints `unchanged:
nothing to write` to stderr instead of `replaced:`/`appended:` lines, still
exits 0, still prints the path, and logs `mode="unchanged"` instead of
`"create"`/`"merge"`. `stats.summarise` counts it in a new `unchanged` field,
shown next to `new`/`merged` in the `writes` line — same shape as
`reject_codes`/`warn_codes` already follow in `stats.py`.

## Rejected alternative

Returning `(path, changed)` from `write_page` was simpler in isolation but
would have required touching every caller (`tests/test_merge.py`,
`tests/test_concurrency.py`, `tests/test_retrieval_quality.py`,
`evals/run.py`, ...) that currently unpacks its return as a single `Path`, for
a fact `main()` can just as easily rediscover itself with two reads.
