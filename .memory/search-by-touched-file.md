---
slug: search-by-touched-file
title: "Search takes the file being edited, not only words"
kind: decision
created: 2026-09-15
updated: 2026-11-04
checked: 2026-11-04T15:26:53+00:00
sources:
  - evals/run.py
  - src/pagelore/search.py
---

## Context

Every page must cite the files it is about — `sources` is required at write
time, and a missing path is a refusal. Ranking never read the field. An agent
about to change `src/terminal/renderer.ts` could only type the path as words,
which tokenise to `src terminal renderer ts` and score on every page under that
directory. Measured on a 50-query `touching` set added to `evals/corpus.json`
(one source path per page, relevant to every page citing it): the right page
came first 38% of the time, nDCG@10 0.545, and words cannot recover it because
77 of the 90 corpus pages never name a source file in title or body.

## Decision

`lore search --touching PATH`, repeatable, with or without query words. The
pages citing that file, or anything under that directory, are ordered first —
by score, recency and slug within the group — and marked `▸ touches <path>` in
the line and `touching: [...]` in `--json`. A file matches only itself, never
its siblings: widening to the directory silently would make `src/` match the
whole store. The supersedes guarantee is untouched: a replacement in the list
still outranks the page it reversed, and a superseded touching page shown alone
carries its marker.

Measured: 0.986 [0.965, 1.000] against 0.545, paired +0.441 [+0.349, +0.539].
The second number is near the ceiling by construction — the relevant set is
defined by the citation — so the number that bought this is the baseline. The
main table did not move, because without the flag the code path is the one it
was.

## Rejected

A score bonus added to BM25F, with a constant to tune. There is no constant
that means "the file the agent is editing", and a fuzzy signal was not what was
asked for: the agent wants the pages about the file before any lexical hit, so
the group ordering is a hard sort key, not a weight. Also rejected: putting
`sources` into the FTS5 index. That is a schema bump and a tokeniser for paths
for a flag that must read every page's frontmatter anyway, so `--touching`
always takes the scan path and says so in `served_by`.
