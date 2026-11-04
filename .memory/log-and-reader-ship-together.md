---
slug: log-and-reader-ship-together
title: "The store logs what happened, and something reads the log"
kind: decision
created: 2026-08-17
updated: 2026-08-17
checked: 2026-11-04T15:26:47+00:00
sources:
  - src/pagelore/stats.py
  - src/pagelore/lib.py
---

## Decision

Every write, refusal and query is appended to `.memory/.log.jsonl`, and
`memory_stats.py` ships with it to read it back: writes and how many were merges,
refusals by code as a share of attempts, and the queries that returned nothing.

## Why the pair, and not just the log

The system this replaced had a reconcile pass that counted source rot correctly
for months into a structure with no consumer. Collecting refusals without a reader
repeats exactly the failure the write gate exists to prevent: a check whose result
nobody collects is indistinguishable from no check.

Three questions it has to settle, which are the ones a trial period asks. Did
agents write at all. Is the gate helping or annoying — a refusal rate that is high
and concentrated on one code usually means the rule is wrong rather than the
writer. Does search find things — queries with zero hits are the strongest signal
there is, pointing at either a hole in the corpus or a hole in ranking.

## Consequences

The log holds real queries and slugs, so it is shielded from git by a `.gitignore`
inside the store rather than by relying on the store's own mode; it stays out of
commits even in a tracked store. Logging never raises: telemetry must not be the
reason a write or a search fails.

What it cannot answer, and honestly should: which page actually answered a query.
The log records the query, the hit count and the top slug, so recall-of-nonzero is
computable and precision is not. Re-tuning ranking would mean hand-grading queries
again from scratch. See [[bm25f-over-hybrid-retrieval]].
