---
slug: static-embeddings-also-refused
title: "Static embeddings are the cheap form of the hybrid, and are refused on the same cost"
kind: decision
created: 2026-09-15
updated: 2026-09-15
checked: 2026-11-04T15:26:54+00:00
sources:
  - evals/dense_probe.py
  - docs/retrieval.md
---

## Context

[[hybrid-rejected-on-cost-not-quality]] refused the embedding hybrid on cost —
a second and a gigabyte per search for +0.046 nDCG@10 — and said the decision
turns the moment the cost goes away. Static embeddings (model2vec `potion`
models: a token-to-vector table, no torch, no ONNX, 30 MB for the small one)
are the cheapest form a dense signal can take. If they cleared the bar, the
refusal was about one model rather than about the design.

## Decision

Refused. `evals/dense_probe.py --static MODEL` runs the same RRF hybrid over a
static model and measures the cold process to one query vector next to the
cold shipped search. The bar, set before running: a hybrid gain of at least
+0.03 with an interval clear of zero, and a cold start under ~200 ms.

| model | hybrid vs shipped | cold process | peak RSS |
|---|---|---|---|
| potion-base-8M | +0.031 [−0.002, +0.063] | 527 ms | 143 MB |
| potion-retrieval-32M | +0.029 [−0.002, +0.063] | 585 ms | 355 MB |
| potion-multilingual-128M | +0.012 [−0.019, +0.042] | 2 218 ms | 1 842 MB |
| shipped search, whole | — | 86 ms | 26 MB |

No interval clears zero, and the cheapest cold start is six times the whole
shipped search. The table loads in tens of milliseconds; the half second is
importing numpy, tokenizers and safetensors, which is the floor for any Python
embedding model in a process that starts fresh per search. So the process model
rules out the cheap version too — and it would buy less quality than the
transformer did, not more.

## What was learned

Dense-only with potion-base-8M scores 0.452 on paraphrase against MiniLM's
0.347: the static model is not the weak link, whole-page embedding is, which
is the same conclusion as before from a second direction. The multilingual
model — the one matching this store's bilingual claim — is worst on every
column at twelve times the memory; the multilingual vocabulary is paid for in
the English rows. Anyone revisiting this should try a chunk-level index inside
a resident process, not a smaller model in this one.
