---
slug: merge-lost-content-silently
title: "Re-running a write used to delete parts of the page it merged into"
kind: bug
created: 2026-08-17
updated: 2026-08-17
checked: 2026-11-04T15:26:47+00:00
sources:
  - src/pagelore/write.py
---

## Cause

`SKILL.md` promised that re-running the same slug section-merges rather than
duplicating, "so a second call is safe". Four separate paths broke that promise,
and every one of them exited 0, printed the page path and logged a successful
write — so nothing downstream could see the loss.

1. `split_sections` treated any line starting with `## ` as a heading, including
   inside a fenced code block. Since the store's own subject is markdown pages, a
   page quoting a page is ordinary: the fence contained a phantom section whose
   chunk held the closing fence and everything after it, and replacing that header
   deleted both.
2. A new body with no `## ` heading became lead-in text, and lead-in was dropped
   whenever the page already had any. Two consecutive prose-only writes to one
   slug lost the second.
3. Frontmatter was rebuilt from a fixed five-key whitelist, so any field a user or
   a later version added was deleted. That silently blocked the cheapest possible
   fix for superseded pages, which is a `supersedes:` field.
4. The 200-character floor was measured against the increment, not the resulting
   page, so a short amendment recording a reversal was refused — the cheapest and
   most valuable write in the system was structurally forbidden.

Replacement also moved the section to the end of the file, so a one-section
amendment read as a whole-file rewrite in `git diff`.

## Fix

Fence-aware splitting; lead-in treated as the section whose header is None and
replaced by the same rule as any other; unknown frontmatter keys preserved
verbatim; the floor applied to the merged result; sections replaced in place.
The command now prints `replaced:` and `appended:` for every section it touched,
because replacing a section is destructive and the default store has no version
control behind it. Regression tests are in tests/test_merge.py.
