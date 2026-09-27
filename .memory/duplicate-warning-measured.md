---
slug: duplicate-warning-measured
title: "lore write does NOT warn on a look-alike page: measured per write, recall collapses (Jaccard 0.09, TF-IDF cosine 0.00)"
kind: decision
created: 2026-09-27
updated: 2026-09-27
sources:
  - evals/duplicate_probe.py
  - src/pagelore/write.py
---

## Why it was asked

An agent sometimes writes a second page on a topic that already has one instead
of amending it (`--slug`) or replacing it (`--supersedes`), which splits a
memory across two pages that drift apart. The question: would a "looks like an
existing page" warning on creation catch this reliably enough to be worth an
agent's attention, and at what cost.

## What was measured

`evals/duplicate_probe.py` runs on the 90-page eval corpus (`evals/corpus.json`,
4005 unordered pairs). The corpus carries no labelled duplicates, so the probe
uses the one signal it does have: the 11 pages that `supersedes` another page
are pairs about the same topic — the positives. Every other pair is a negative,
an approximation, since the corpus was written to cover distinct topics, not
guaranteed distinct.

Two measures over `search.tokenize(title + " " + body)`: **Jaccard** of token
sets, and **TF-IDF cosine** with IDF from `search._idf` (the same Lucene-IDF
formula the shipped ranker scores with).

A first pass measured these **per pair**: threshold = smallest value keeping
the false-positive rate over the 3994 negative pairs at or below 1%, recall
measured on the 11 positive pairs at that threshold.

- Jaccard: threshold 0.1684, FP rate 0.93%, recall **0.818**.
- TF-IDF cosine: threshold 0.2102, FP rate 0.98%, recall **0.636**.

This looked like a clear build. It was the wrong unit. `lore write` does not
compare one pair — it compares one new page against every OTHER page in the
store and warns on the single best match. At 90 pages that is 90 chances per
write for some unrelated page to score high by accident, not one chance per
pair. A 1%-per-pair budget does not bound the per-write false-warning rate at
all.

Re-measured **per write**: each of the 90 pages in turn stands in as the page
being newly created, scored against the other 89; the best-scoring other page
is the one that would be reported. A write is a false warning if that best
score clears the threshold and the best match is NOT the page's actual
`supersedes` partner; a true warning if it clears the threshold and the best
match IS the partner. Threshold = smallest value keeping false warnings at or
below 1% of the 90 writes (which rounds down to 0 false warnings admitted, at
this corpus size — 1 false warning out of 90 is already 1.11%). Recall = true
warnings / 22, the number of writes that have a correct answer to reach (both
directions of each of the 11 supersedes pairs).

- Jaccard: threshold 0.2102, recall **0.091** (2 of 22), 0 false warnings.
- TF-IDF cosine: threshold 0.4048, recall **0.000** (0 of 22), 0 false
  warnings.

Why the collapse: by hand-checking, the single highest-scoring UNRELATED pair
in the whole corpus, by both measures, is `sync-updater-signature-chain` /
`platform-updater-signature-key-rotation` (Jaccard 0.2102, TF-IDF cosine
0.4048) — topically adjacent (both about update/signature/rotation mechanics)
but genuinely different decisions, neither superseding the other. Its score is
at or above most of the real duplicate pairs' scores (Jaccard positives median
0.183, max 0.227), so any threshold low enough to catch most real duplicates
also catches this pair (and others like it — `sync-lww-per-field-rejected` /
`platform-settings-sync-excluded-keys` at 0.209, `pty-reap-sigchld-selfpipe` /
`pty-eof-drain-race-lost-output` at 0.206) on nearly every write where either
page is involved, and any threshold high enough to exclude all of them also
excludes almost every real duplicate. The per-pair unit hid this because a
handful of bad pairs among 3994 negatives is invisible in an aggregate
false-positive rate; the per-write unit exposes it because a bad pair is the
single best match for whichever of its two pages is being "written" — one bad
pair is enough to spoil that write outright, and there turned out to be more
than one.

## Decision

**Not built.** The decision rule (recall >= 0.5 at <= 1% false warnings,
fixed before either unit's numbers existed) is applied to the per-write
number, since that is the unit the feature actually operates in — a per-pair
number answers a question `lore write` never asks. Neither measure clears the
floor per write (0.091 and 0.000, against 0.5 required).

`src/pagelore/write.py` carries no feature from this probe: the write path
was briefly changed to add `find_similar`/`LOOKS_LIKE_THRESHOLD` on the
per-pair numbers, then reverted in full once the per-write re-measurement
came back, before anything was committed. `write.py` stays a cited source
here only because this page's history includes that reverted attempt, not
because the shipped file does anything described above.

## Cost

Moot, since nothing was built. For the record: the reverted implementation
was measured at 41.0 ms -> 291.7 ms median (a real `lore write` subprocess,
1000-page store, creating a new page) — the cost of tokenizing every
candidate page's title+body from scratch on every single creation, no
caching. Not a reason by itself to reject the feature (that was the recall
number), but confirms this would not have been a free warning even if it had
worked.

## What would change the answer

A corpus with real, non-supersedes duplicate pairs, so recall could be
measured against actual near-duplicates instead of approximating "different
topic" as "not a supersedes pair" — this corpus's shared domain vocabulary
(every page is about the same fictional project) makes topically-adjacent
non-duplicates score close to real duplicates, which is exactly what sank the
per-write recall here. A different similarity signal that separates "same
project, adjacent subsystem" from "same page, reworded" better than
title+body token overlap does — title-only similarity, or a higher weight on
rarer shared terms, might avoid the `sync-updater-signature-chain` /
`platform-updater-signature-key-rotation` collision without giving up recall
on true duplicates. Worth re-running this probe if either becomes available.
