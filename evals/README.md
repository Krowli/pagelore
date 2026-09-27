# Evaluation

```bash
python3 evals/run.py --by-type
```

Everything this needs is committed here: the corpus, the queries, the methods and
the scorer. That is the entire point. `references/retrieval.md` used to argue the
design from figures whose inputs existed in nobody's repository — no reader could
check them, and no future change could be re-measured against them.

## What is measured

**Known-item retrieval.** Each query was written for exactly one page, and the
question is where that page lands. Reported as nDCG@10, MRR@10, recall@1 and
recall@3, with a bootstrap confidence interval over queries (1000 resamples). A
difference smaller than the interval is not a difference.

**Ambiguous queries.** Several pages are legitimately relevant. This separates
"found something" from "put the best one first", which the known-item set cannot.

**Unanswerable queries.** Realistic questions about the same project that no page
answers. A ranked list invites false confidence: the interface always returns
*something*, and an agent reads a list as an answer. The number reported is the
share of these queries that got any hit at all — lower is better, and no amount of
ranking quality compensates for it.

**Touching queries.** Fifty source paths, one per page, each relevant to every
page that cites it. This is the agent that knows which file it is editing rather
than which words a page used, and it measures `--touching` against typing the
path as words. The relevant set is defined by the citation, so the flag's row is
near the ceiling by construction; the informative row is the baseline, which is
what today costs. See `references/retrieval.md`.

## Methods compared

| method | what it stands for |
|---|---|
| `shipped (fts5 index)` | what an installed skill actually runs — so the number is the number users get |
| `shipped fallback (scan)` | the path that answers on a read-only store, mid-rebuild, or without sqlite3 |
| `scan, title weight 0` | ablation of the parameter the documentation calls the most important |
| `term count (previous)` | what this skill used before BM25F |
| `fts5 on raw text` | FTS5 with its own tokenizer — the variant that loses NFC, casefold and identifiers |
| `grep -rilE` | no ranker at all: every page containing any query word, in filename order |

## Does the store help the agent

`evals/run.py` measures retrieval. It does not measure the thing that matters, which is
whether an agent *answers better* because the store exists. `evals/agent_loop.json` records
one run of that, question by question, with every search the agent ran and every page it
opened.

Protocol: the 90-page corpus is written out as a real store; 18 questions in three families
are put to an agent that has the store and the skill's instruction; the same questions, minus
the ones only the store could answer, go to a control agent with no store at all; a grader
scores both against gold facts fixed before the answers existed.

| | with the store | control, no store |
|---|---|---|
| **answerable** (8) — the answer is in exactly one page | 8 correct | not run |
| **unanswerable** (5) — no page answers it | 5 abstained | 5 abstained |
| **superseded** (5) — a decision was reversed; asks what holds *now* | 5 correct, 0 obsolete | 5 abstained |

The superseded row is the one worth having. It is the failure the README opens with, and the
agent gave the current decision every time — following the `superseded by` marker to the
replacement rather than answering from the page it found first.

Median effort per question: 2 searches and 2 pages read when the answer exists, and **6
searches** before concluding it does not. That second number is the cost of the fact measured
above — a search practically never comes back empty, so establishing absence is work.

### What this run does not establish

- **The control is weak.** It was told "if you do not know, say so plainly", which primes the
  abstention it then produced. So the unanswerable row shows the store did not *cause*
  confabulation; it cannot show that the store prevents any.
- **The project is fictional**, so a model has no prior knowledge to confabulate from.
  Abstaining is easier here than on a real codebase, where the temptation to fill a gap from
  training data is real. Read that row as an upper bound.
- **Adherence is not tested.** The agent was told to search. Whether an agent searches when
  nobody reminds it in the moment is what `acceptance.py` checks, per harness, and this
  measures the loop working when the agent cooperates, not how often it does.
- One run, 18 questions, one grader per batch, questions written by a model from the corpus.

## Against the closest competitor

`evals/compare_basic_memory.py` runs Basic Memory 0.22.1 over the same 90 pages and
the same 270 queries, scored by the same scorer. It is the one system in the field
making the same core bet — markdown on disk, human-editable, git-friendly — and it
adds what this skill does not have: a persistent hybrid index (SQLite FTS plus
local embeddings, 90 entities embedded here) and a real link graph. It needs no API
key, which is why it can be measured honestly and mem0 cannot.

| | shipped | basic-memory |
|---|---|---|
| overall nDCG@10 | 0.649 | 0.640 |
| keywords | 0.792 | **0.830** |
| paraphrase | **0.532** | 0.481 |
| prose | 0.622 | 0.609 |

Paired difference **+0.009 [−0.040, +0.058] — not significant.** On this corpus the
two are indistinguishable overall. The split is the interesting part: the hybrid
system is better on bare keywords and *worse* on paraphrase, which is the second
independent sign here that adding embeddings does not automatically buy the thing
embeddings are supposed to buy (see `dense_probe.py`, where dense-only scored 0.347
on paraphrase against the lexical ranker's 0.532).

**What this does not say.** Both systems ran at their defaults, on one corpus, with
a query set written against these pages rather than by either project. Latency is
not comparable and is deliberately not quoted as a result: Basic Memory is designed
to run as a long-lived MCP server, and measuring it through a fresh CLI process per
query measures process startup and model loading, not the product. Its link graph,
its sync and its editing tools are not exercised at all — this compares one axis,
retrieval quality, and nothing else.

**mem0 will not be measured here, and that is a decision rather than a gap.** Its
pipeline extracts facts with an LLM, so a run needs an API key and spends money;
substituting a small local model would produce a number that could not honestly
carry the name. It is also a different class of system — conversational memory that
stores extracted facts, not documents — so feeding it pre-written pages and asking
known-item questions would measure it on a task it was never built for. A low score
would mean "mem0 does something else", which is already known and needs no
benchmark to say.

## What this cannot tell you

**The corpus and the queries were written by a language model.** They are not
harvested from a real store, and that is a real limitation, not a footnote.

The specific danger is that a query written from a page tends to reuse that page's
distinctive words, which flatters lexical retrieval and would make these numbers
optimistic. Two things push against it, and neither removes it:

- every page carries three queries of different types, and the `paraphrase` type is
  explicitly written to describe the same thing in *different* vocabulary — the
  symptom instead of the cause, the user-visible effect instead of the internal name;
- the per-type table is the one to read. If `keywords` and `paraphrase` diverge
  sharply, that gap is the vocabulary-mismatch weakness of lexical search showing
  up, and the average across types hides it.

**One competitor is measured, not the field.** Basic Memory is above, and the
embedding hybrid is in `dense_probe.py`. Zep, Letta, cipher and the rest are not:
each needs its own stack running over this corpus, and until someone does that, any
claim that this skill retrieves better than those remains a hypothesis. What the
harness supports is narrower — how the shipped ranker compares to the alternatives
that need no server, and whether its own documented parameters earn their place.

**Retrieval quality is not the product.** Whether an agent gives better answers
because this store exists is a different question, and this harness does not touch
it.

## Would an import graph help `--touching`

`evals/import_probe.py --repo PATH` measures a feature before it exists: `lore
search --touching FILE` only surfaces pages that name FILE directly, so it is
useless for a file no page cites. The question is whether walking one hop over
the import graph (FILE imports X, or X imports FILE, and X *is* cited) would find
real pages more often than noise, on a real repository with a real `.memory/`.
It parses Python (`ast`), TS/JS (regex, relative specifiers only) and Rust
(`mod`/`use crate`/`super`/`self`) well enough to build that graph from
`git ls-files`, then reports coverage, reach, noise at three hub caps and a
leave-one-out recall, against a build threshold fixed before any repository was
measured. Run on this repository itself the answer is "do not build": reach and
leave-one-out recall both come in under threshold, because coverage here is
already high enough (most source files are already cited directly) that few
files are left for a graph hop to rescue.

## Regenerating the corpus

`corpus.json` is committed so the numbers are reproducible. It was generated by
six agents writing about distinct subsystems of one fictional project, plus one
pass for the ambiguous and unanswerable sets. Regenerating it changes the numbers;
if you do, say so next to any figure you quote from it.
