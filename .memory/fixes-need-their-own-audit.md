---
slug: fixes-need-their-own-audit
title: "The first round of fixes introduced three of its own bugs"
kind: bug
created: 2026-08-17
updated: 2026-08-17
checked: 2026-11-04T15:26:47+00:00
sources:
  - src/pagelore/write.py
  - src/pagelore/lib.py
---

## What happened

A round of fixes for silent data loss was reviewed by agents whose only task was
to break them. They broke three, and all three were *caused* by the fixes:

- Replacing sections in place required knowing which stored section to replace,
  and the incoming sections were built as a dict — so two sections sharing a
  header lost the first copy on a merge, while a new page kept both.
- The fence fix matched exactly three backticks. Quoting a memory page — the case
  the fix exists for — requires a longer outer fence, and the first inner ```
  closed it, so the bug survived in exactly its motivating scenario.
- The read path was taught to skip symlinks leaving the store. The write path,
  added in the same changeset, was not: `--supersedes` on such a page read the
  target and wrote its contents into the store as a real page, so the next search
  printed the secret the read guard had just been written to hide.

## Why it kept passing

Every one of these had a test, and every test passed. The supersession tests were
worse than useless: the mechanism could be deleted entirely and the suite stayed
green, because the fixture gave both pages the same title and body, so the
alphabetical tie-break happened to order them correctly.

## What changed as a result

Tests here are checked by removing the fix and confirming the suite goes red —
`/private/tmp` scratch script, eleven guards, all eleven caught. A fixture that
must be a hard case now asserts that it is one before the test that depends on it
runs. And a test whose regression would *hang* rather than fail runs in a
subprocess with a timeout, because a CI job that never finishes is a worse signal
than one that fails.

The general lesson is narrower than "write better tests": a fix and its test are
written from the same wrong mental model, so the test inherits the blind spot.
Only an adversary with no stake in the fix finds that. See
[[merge-lost-content-silently]] and [[supersede-rather-than-two-current-pages]].
