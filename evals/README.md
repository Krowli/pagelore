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

## CI gates

Four checks run on every push and PR, not only when someone remembers to run
`evals/run.py` by hand:

- **Retrieval quality.** `tests/test_evals_baseline.py` runs the two shipped
  methods (`shipped (fts5 index)`, `shipped fallback (scan)`) in-process — no
  subprocess, and none of the other methods above, which is most of the cost of
  a full run — and fails if any metric in `evals/baseline.json` regresses by more
  than 0.005 (the opposite direction for `unanswerable answered_anyway`, where
  lower is better). It runs twice in CI, with and without `PAGELORE_NO_FTS5`;
  `baseline.json` keeps separate `fts5` and `scan` sections because the two
  shipped methods become the identical code path under that variable (see the
  test's own module docstring for why one baseline would be wrong in the other
  mode). **To update it on purpose** — after a change that improves ranking, in
  the same PR — regenerate both sections:

  ```bash
  python3 evals/run.py --json                       # fts5 section
  PAGELORE_NO_FTS5=1 python3 evals/run.py --json     # scan section
  ```

  and copy `shipped (fts5 index)`, `shipped fallback (scan)` and
  `_touching.methods["path as text query"]` from each into the matching section
  of `evals/baseline.json`. Never edit the file to make a failing gate pass
  without knowing why the number moved.
- **Speed.** A `speed-gate` job runs `evals/speed.py --pages 1000` against the
  wheel it just installed (`lore` resolved from `PATH`, not this checkout) and
  fails if the warm, indexed search exceeds 1000 ms — about 12x today's local
  number, to absorb a noisy runner without absorbing a real regression.
- **The MCP round trip.** `install-smoke`'s MCP step drives `tools/call` over
  `lore mcp`'s stdio, not just `tools/list`: a `memory_write` lands a real page,
  a `memory_search` finds it back, and a write whose body contains a
  credential-shaped string is refused with the same `FIX:` line the CLI prints.
- **Documented examples.** `tests/test_docs_examples.py` collects every `lore …`
  line in a fenced code block across the docs and checks it against the real
  `argparse` parser for that subcommand, without running the command. A renamed
  or removed flag breaks the build instead of quietly going stale in a doc.

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

## How does a real agent use the memory, behaviour by behaviour

`acceptance.py` answers one yes/no — did any search land — for one session, and keeps
nothing. Real logs show behaviours that question cannot see: the same top page returned
three to five times to reworded queries, `--touching` never used, no page written after a
fix. `evals/agent_eval.py` runs a real Claude Code agent through six fixed tasks (A–F), many
times, keeps every session, and puts a number with an interval on each behaviour, so an
instruction change can be accepted or rejected on evidence.

```bash
python3 evals/agent_eval.py --label baseline          # 2 arms × 6 tasks × 10 runs, sequential
python3 evals/agent_eval.py --models claude-opus-5-5,claude-sonnet-5 --label baseline
python3 evals/agent_eval.py --arms mcp --tasks C --runs 3 --label try
python3 evals/agent_eval.py --dry-run --tasks C       # build the projects, print the commands
python3 evals/agent_eval.py --summarize evals/results/agent-…-baseline.jsonl \
                                        evals/results/agent-…-guidance.jsonl
```

Needs `claude` on PATH and logged in. `lore` in the sessions is a shim to this working tree
(`PAGELORE_BIN` overrides what it runs), and the run refuses to start unless it reports this
tree's version and directory. Results append to
`evals/results/agent-<date>-<version>-<label>.jsonl`, one header line and then one line per
session the moment it ends; an existing file is refused unless `--append` is given.
`--models` runs each cell once per model (default: whatever the CLI picks), and the model the
session reports is recorded and grouped on. `--summarize` accepts one file or two and `--json`; it re-scores every session from its raw
tool calls, answer and log with the current rules, and says so per file when the stored
metrics differ, so files written by different harness versions compare under one rulebook.

**Arms.** `include`: the project's CLAUDE.md is the one `@path` line `lore init` writes.
`mcp`: no instruction file, a `.mcp.json` whose server `pagelore` is this tree's `lore mcp`.
Both run with `--strict-mcp-config` — without it the user's claude.ai connectors (mail,
drive) load into the session, which pollutes the measurement and shows an eval agent the
user's mail.

**Tasks** (`agent_tasks.json`, all on corpus pages): **A** a "why was this decided" question
answered by one page; **B** a question no page answers; **C** an edit to a file a page
constrains; **D** a question whose first page was superseded; **E** a non-obvious bug to fix;
**F** a question worded without the vocabulary of the page that answers it, which invites
reworded searches. `n_searches` and `repeats` on B and F are the churn measures.

| metric | meaning |
|---|---|
| `searched` | the store logged at least one search in the session |
| `correct` | A, D, F: the answer carries a fact only the right page has (`answer_any`, each phrase checked against the page text by a test, so general knowledge cannot score); B: the answer says the memory lacks it (`abstain_any`); C: the answer names the page's measured constraint; E: not graded |
| `obsolete` | D: the answer states the superseded decision's facts and none of the current one's (`endorses_obsolete`); history next to the current decision does not count |
| `srch<edit` | the first search call came before the first Edit/Write outside the store; sessions that edited nothing are left out of the denominator |
| `touching` | some search passed `--touching` / `touching` |
| `wrote` | the store logged a page write (`lore write` or `memory_write`) — the point of task E |
| `grep_mem` | scanned `.memory` around the command: Grep/Glob into it or over the whole project (no path, `.`, the root), or grep -r / find / git grep / `cd .memory` in Bash |
| `read_mem` | opened a page file directly (Read, or cat/head/sed). Counted apart from `grep_mem` because the MCP arm has no `show`, so reading the file is how it opens a hit |
| `med srch` / `mean rep` | searches per session; searches whose top hit repeats an earlier top hit |
| `med turn` / `med $` | turns and cost per session, from the result event |

Rates carry Wilson 95% intervals. With two files, each row also gets B − A with a Newcombe
95% interval and Fisher's exact two-sided p for rates, and both medians with a Mann-Whitney U
p (normal approximation — rough below about eight sessions a side) for searches, repeats,
turns and cost; p < 0.05 is starred. Also recorded per session: the requested and reported
model, the Claude Code version, the full tool sequence, the answer, and the store's log lines.

**The environment is part of the measurement.** A local run happens inside the user's own
Claude Code: `--setting-sources project` keeps user settings out, but the user's skills and
plugins still load, and the header and each session record how many. So a comparison is only
valid when both files were run in the same environment, paired — same machine, same Claude
Code, same model — and the summary prints those fields per file so a mismatch is visible.

**CI.** `.github/workflows/agent-eval.yml`, `workflow_dispatch` only (inputs `arms`, `tasks`,
`runs` default 3, `label`, `models`), needs the `ANTHROPIC_API_KEY` secret, prints the summary and
uploads the results file as an artifact. Nothing else in CI runs it.

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
`git ls-files`, then reports coverage once, plus reach, leave-one-out recall and
noise (median group size over non-empty groups) computed separately at each of
three hub caps — inf, 10, 5; a hub is a file imported by more than N others, and
a hub neighbour is dropped from a group rather than counted, since one hop from
a widely-shared module says nothing specific. The verdict picks the first cap,
in that order, whose three numbers all clear a build threshold fixed before any
repository was measured — not cap inf unconditionally, because the shipped
feature would use whichever cap the probe recommends. Run on this repository
itself the answer is "build (hub cap 10)": at cap inf every widely-imported
module (`cli.py`, `lib.py`, `search.py`, ...) drags in every page that mentions
it, so the median non-empty group is 9 pages — well over the noise threshold —
but capping at 10 drops just enough of that traffic to bring it down to 1 page
while reach (32%) and leave-one-out recall (55%) still clear their thresholds
comfortably.

## Would a "looks like an existing page" warning help `lore write`

`evals/duplicate_probe.py` measures a feature before it exists: whether `lore
write` could warn, on creation, that a new page looks like one already in the
store — the failure this catches is an agent writing a second page on a topic
that already has one, instead of amending it or superseding it. The corpus has
no labelled duplicates, so the probe uses the one signal it does carry: the 11
pages that `supersedes` another page are pairs about the same topic, and every
other of the 4005 unordered pairs is treated as a negative (an approximation —
the corpus was written to cover distinct topics, not guaranteed distinct).

Two measures over `search.tokenize(title + " " + body)` — Jaccard over token
sets, and TF-IDF cosine with IDF from `search._idf`. Two units, because the
first pass measured the wrong one: **per pair**, scored by the smallest
threshold that holds the false-positive rate at or below 1% over the 3994
negative pairs, recovers 0.818 recall (Jaccard) — but a write does not compare
one pair, it compares one new page against every other page in the store and
warns on the single best match, which is 90 chances per write for an unrelated
page to score high by accident, not one. Re-measured **per write** — each of
the 90 pages in turn as the page being created, against the other 89, false
warnings budgeted at 1% of the 90 writes, recall over the 22 writes that have a
correct answer (both directions of the 11 supersedes pairs) — recall collapses
to 0.091 (Jaccard) / 0.000 (TF-IDF cosine): the highest-scoring unrelated page
in the corpus, `sync-updater-signature-chain` / `platform-updater-signature-key-rotation`
(see the memory page), scores as high as or higher than most of the genuine
duplicate pairs, so a threshold tight enough to exclude it excludes almost
everything else too.

The decision was made on the per-write number, per the rule fixed before either
number existed (build if recall >= 0.5 at <= 1% false warnings): **not built**.
See `.memory/duplicate-warning-measured.md` for the full numbers from both
units and why the per-pair unit was the wrong one to decide on.

## Regenerating the corpus

`corpus.json` is committed so the numbers are reproducible. It was generated by
six agents writing about distinct subsystems of one fictional project, plus one
pass for the ambiguous and unanswerable sets. Regenerating it changes the numbers;
if you do, say so next to any figure you quote from it.
