---
slug: hybrid-rejected-on-cost-not-quality
title: "The embedding hybrid is better, and is still refused — on cost, not quality"
kind: decision
created: 2026-08-18
updated: 2026-08-18
checked: 2026-11-04T15:26:54+00:00
supersedes:
  - bm25f-over-hybrid-retrieval
sources:
  - evals/dense_probe.py
  - docs/retrieval.md
---

## What changed

The earlier page said the hybrid's gain was "paid and inside the noise", citing
+0.032 nDCG@10 with an interval two thousandths from zero, from a corpus that
exists in no repository. Re-measured on the corpus in `evals/`, with reciprocal
rank fusion over `paraphrase-multilingual-MiniLM-L12-v2`, the gain is **+0.046
[+0.014, +0.075]** — real, and clear of zero. Quality is not the reason to refuse
it, and saying so was wrong.

## The actual reason

The skill is a script run afresh for every search. So the embedding model is
loaded on every invocation, and that costs about **1000 ms and 1.06 GB of resident
memory** against a **72 ms** whole search today. Fourteen times the latency and a
gigabyte of RAM, per search, to buy 0.046.

The trade is only bad because of the process model. Anything that keeps the model
resident — a daemon, a long-lived server — flips it, and a daemon is the one thing
this design refuses to have. So this is a constraint-driven decision, not a
quality one, and it should be revisited the moment that constraint changes. The
harness to decide it with is committed.

## Two things worth keeping

Dense retrieval was **worst exactly where it was supposed to win**: 0.347 on
paraphrase queries against the lexical ranker's 0.532. Whole-page embedding of
1.5 KB documents dilutes the signal. That rules out the cheap version of the idea,
not the idea — a chunk-level index is untested here.

And a measurement error worth remembering: `fastembed` does not normalise this
model's output, so a raw dot product ranks by document length as much as by
meaning. The first run did that and reported the gain as not significant — the
wrong answer, in the direction that happened to flatter this project. See
[[fixes-need-their-own-audit]].
