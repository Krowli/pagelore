---
slug: supersede-rather-than-two-current-pages
title: "A reversed decision is marked, demoted, and kept"
kind: decision
created: 2026-08-17
updated: 2026-08-17
checked: 2026-11-04T15:26:47+00:00
sources:
  - src/pagelore/search.py
  - src/pagelore/write.py
---

## Context

The README opens with the failure this project exists to fix: agents confidently
restate decisions that were reversed months ago. The store could not express that.
A reversal recorded as a new page left two pages that both read as current;
ranking had no recency or authority term, ordering ties alphabetically by slug;
and neither the printed line nor the JSON output carried `created` or `updated`,
even though every page has them. A March decision could and did outrank its own
June reversal.

## Decision

`--supersedes <slug>` on the new page. The old page is stamped `status:
superseded` and `superseded_by: <new-slug>`, scored at half its BM25F score, and
marked in every result line. It stays searchable, because what was rejected and
why is often the useful part — it just stops outranking its replacement.
`--supersedes` naming a slug that is not in the store is refused, so a typo does
not silently record nothing.

Recency is a tie-break, not a score term: equal scores prefer the more recently
updated page. The published evidence on adding a recency or decay term to the
score is negative, and preferring a fresher page only when the relevance evidence
is equal is the part that is defensible.

## Consequences

This is deliberately manual. Detecting a contradiction between two pages without
being told needs either an LLM in the write path or a schema this format does not
have, and both were more machinery than the problem justifies. The tool's job is
to make the reversal expressible and impossible to miss once recorded.

## Why the demotion is not a weight

The first implementation scored a superseded page at half its BM25F score and
stopped there. That is not the guarantee the feature exists for, and it failed on
the first realistic pair it met: "Auth uses server-side sessions", superseded,
scored 0.5 against its own replacement's 0.4 and came out on top.

The reason is structural rather than a bad constant. A decision page names the
option it rejected — "sessions in Redis, not JWT" — so the old page matches a
query mentioning both options better than the new page, which only names what it
chose. Tuning the weight down until this particular pair flips would bury
legitimately relevant old pages for every other query.

So the ordering is corrected pairwise, in `lift_superseders`: after ranking, a
page is moved ahead of anything it superseded, and nothing else moves. The score
demotion stays for the case where the replacement is not in the result set at all.
The correction runs before `k` truncates, or the page that answers the question
becomes the one that falls off the end of the list.

The lesson for tests here: the first version of this test gave both pages the same
title and body, so it verified the arithmetic of the demotion instead of the
guarantee. It passed while the feature was broken. The test now uses the case that
actually failed.
