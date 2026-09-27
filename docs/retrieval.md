# Retrieval

`lore search` has two paths and one ordering. A persistent SQLite FTS5 index
(`index.py`) answers when it can; otherwise every page is read and scored
in process with the BM25F below. Both drop zero scores and return the top `k`. Ordering is score, then the
more recently `updated` page, then slug — alphabetical order used to decide which
of two equally scored pages the agent read first, which is how a reversed decision
could come out on top of the decision that reversed it. A page carrying
`superseded_by` is scored at `SUPERSEDED_WEIGHT` (0.5) of its BM25F score, so it
stays findable without outranking its replacement. Only top-level `*.md` files are
indexed. There is no server.

## Why BM25F — measured, reproducibly

```bash
python3 evals/run.py --by-type
```

90 pages, 270 known-item queries, 12 ambiguous, 20 unanswerable. Corpus, queries,
methods and scorer are all committed under `evals/`. Confidence intervals are a
bootstrap over queries; the comparisons are **paired**, because every method sees
the same queries.

| method | nDCG@10 | vs shipped, paired |
|---|---|---|
| **shipped, FTS5 index** | **0.649** | — |
| shipped fallback, in-process BM25F | 0.644 | +0.004 [−0.009, +0.018] — **not a difference** |
| scan with the title weight at 0 | 0.595 | +0.054 [+0.027, +0.081] |
| term-count scoring | 0.432 | +0.216 [+0.164, +0.267] |
| `grep -rilE` (unranked) | 0.113 | +0.535 [+0.480, +0.586] |

Three things follow.

**Ranking earns its place against what it replaced.** Term counting is 0.216
nDCG@10 worse, far outside the interval. Unranked grep is not in the same
discipline at all — it is 0.535 behind, because it returns every page sharing any
word, in filename order.

**The title weight is real but modest**: +0.054 [+0.027, +0.081]. An earlier,
unreproducible measurement recorded +0.069; direction and rough size hold up.
`tests/test_retrieval_quality.py` fails if it goes back to zero.

**The two shipped paths are indistinguishable in quality**, which is what makes
the index safe to prefer: it is chosen for speed, and it costs nothing in what the
agent actually gets back. Choosing between the formulas on quality grounds would
be reading noise.

### The hybrid, re-measured — and the stated reason was wrong

`evals/dense_probe.py` (optional: needs `fastembed`, downloads a model, which the
skill itself never does) runs dense and hybrid retrieval over the same 90 pages and
270 queries, with `paraphrase-multilingual-MiniLM-L12-v2` and reciprocal rank
fusion.

| method | nDCG@10 | vs shipped, paired | keywords | paraphrase | prose |
|---|---|---|---|---|---|
| shipped | 0.649 | — | 0.792 | 0.532 | 0.622 |
| dense only | 0.582 | −0.067 [−0.125, −0.013] | 0.757 | **0.347** | 0.640 |
| hybrid (RRF) | **0.695** | **+0.046 [+0.014, +0.075]** | 0.830 | 0.535 | 0.719 |

**The hybrid is genuinely better, and this document used to say it was not.** The
earlier claim — a +0.032 gain whose interval "sits two thousandths from zero" —
does not hold here: on this corpus the gain is +0.046 and the interval is clear of
zero. Quality is not the reason to refuse it.

The reason is architecture, and it is much larger than the quality difference. The
skill is a script run afresh for every search, so the model is loaded every time:

| | |
|---|---|
| whole search, as the agent runs it | **72 ms** |
| cold process to a single query vector | **~1000 ms**, peak RSS **1.06 GB** |

Fourteen times the latency and a gigabyte of resident memory, per search, for
+0.046. That trade only changes if something keeps the model resident — a daemon,
which is the one thing this design refuses to have. If that constraint ever goes
away, this is the first thing to revisit, and the harness to decide it with is
already here.

One finding worth keeping regardless: **dense retrieval is worst exactly where it
is supposed to win.** On paraphrase queries — written deliberately in different
vocabulary from the page — it scores 0.347 against the lexical ranker's 0.532.
Whole-page embedding of ~1.5 KB documents dilutes the signal, and a chunk-level
index might behave differently; what this rules out is the cheap version of the
idea, not the idea.

A note on measuring it: `fastembed` does not normalise this model's output
(measured norms 3.4 and 4.9), so a raw dot product ranks by document length as
much as by meaning. The first run of this probe did exactly that and reported the
hybrid gain as *not* significant. The correction is in the script.

### Static embeddings, the cheap form of the idea — also refused

The cost objection above is the transformer's: a gigabyte resident and a second
to load. Static embeddings (model2vec's `potion` models: a token-to-vector table,
no torch, no ONNX) are the cheapest form a dense signal can take, so
`dense_probe.py --static MODEL` runs the same hybrid over them. Bar to clear,
set before running: a hybrid gain of at least +0.03 nDCG@10 with an interval
clear of zero, and a cold process to one query vector under ~200 ms.

| model | on disk | hybrid vs shipped, paired | cold process to a vector | peak RSS |
|---|---|---|---|---|
| `potion-base-8M` (English) | 30 MB | +0.031 [−0.002, +0.063] | **527 ms** | 143 MB |
| `potion-retrieval-32M` (English) | 129 MB | +0.029 [−0.002, +0.063] | 585 ms | 355 MB |
| `potion-multilingual-128M` | 512 MB | +0.012 [−0.019, +0.042] | 2 218 ms | 1 842 MB |
| shipped search, whole, cold | — | — | 86 ms | 26 MB |

Every row fails both halves of the bar: no interval is clear of zero, and the
cheapest cold start is six times the whole shipped search. The table itself
loads in tens of milliseconds; the ~500 ms is importing numpy, tokenizers and
safetensors, which is the floor for any Python embedding model and is what a
per-search script pays. So the process model rules out the cheap version of
the idea too, not only the expensive one — and the quality it would buy here is
smaller than the transformer's +0.046, not larger.

Two smaller findings. Dense-only with `potion-base-8M` scores 0.452 on
paraphrase, better than MiniLM's 0.347, so the static model is not the weak
link — the whole-page embedding is. And the multilingual model, the one that
matches this store's bilingual claim, is the worst of the three on every column
(0.394 on paraphrase) at twelve times the memory: multilingual vocabulary is
paid for in the English rows.
### Searching by file: `--touching`

Every page must cite the files it is about, and until 0.2.2 ranking never read
that field. An agent about to change `src/terminal/renderer.ts` could only type
the path as words — which tokenises to `src terminal renderer ts`, terms that
score on every page under `src/terminal/`. `evals/corpus.json` carries a
`touching` set for this: 50 source paths taken one per page, each relevant to
every page that cites it (29 paths cite one page, 21 cite two to seven).

| the path given as | nDCG@10 | R@1 |
|---|---|---|
| query words | 0.545 [0.450, 0.638] | 0.380 |
| `--touching` | **0.986** [0.965, 1.000] | 0.960 |

Paired: **+0.441 [+0.349, +0.539]**. Read the second row for what it is — the
relevant set is *defined* by the citation, so a flag that puts cited pages first
is close to the ceiling by construction. The row worth having is the first: the
right page comes first for 38% of path queries today, and the number is not
recoverable from words because 77 of the 90 pages never mention a source file's
name in title or body. The two queries short of 1.0 are a superseded page whose
replacement cites a different file; the replacement is lifted above it, as
everywhere else, and the marker on the old page says why.

`--touching` orders the pages that cite the file (or anything under the
directory) first, by score within the group, and leaves everything else exactly
as it was: no flag, no change, and the table above did not move. Sources are not
in the FTS5 index, so a `--touching` search reads every page — the scan path's
cost, paid only when asked for.

### The historical figures

An earlier version of this document argued the design from a private measurement:
110 real agent queries from a production store's call log, 3 984 hand-graded
pairs, three judges, kappa 0.69–0.73. **Those artifacts are in no repository**, so
no reader could check them. They are kept here only as the record of why the
choice was made, and everything load-bearing has since been re-measured above.

| method | nDCG@10 | 95% CI |
|---|---|---|
| hybrid BM25 + bge-m3 via RRF | 0.788 | [0.759, 0.817] |
| **BM25F (this)** | **0.757** | [0.726, 0.787] |
| dense, chunk-level | 0.696 | [0.659, 0.732] |
| dense, whole-page | 0.683 | [0.644, 0.720] |
| term-count scoring | 0.660 | [0.612, 0.705] |

Two deltas decided it. Term-count → BM25F is **+0.097 [+0.053, +0.144], p=0.0001**
and costs nothing. BM25F → hybrid is **+0.032 [+0.002, +0.061], p=0.041** — an
interval whose lower bound sits two thousandths from zero — and costs a resident
1.2 GB embedding model, ~95 ms added to every query (1.27 s if the model has been
evicted), and 286 s to build the index for 491 pages. The first delta is free and
large; the second is paid and inside the noise.

Dense retrieval is not uniformly better even where it is supposed to win. On the
plural query type — bag-of-keywords, 55% of the real log — it is **−0.113
[−0.163, −0.064], p=0.0001** against BM25F. It gains on conceptual prose
(+0.056, p=0.085, interval crosses zero). Failure mode observed by the judges:
`bge-m3` answers the query `sidecar` with `sidebar-*` pages.

## The index, and why it is only a cache

The pages are the memory. The index says which file to open, nothing more, and any
doubt at all falls back to reading the markdown — slower, never stale, never a
traceback. Measured end to end, as a shell invocation, on this machine:

| pages | reading every page | warm index | |
|---|---|---|---|
| 90 | 76 ms | 52 ms | 1.5x |
| 1000 | 341 ms | 69 ms | 4.9x |
| 5000 | 1507 ms | 139 ms | 10.8x |

`python3 evals/speed.py`, one search end to end as a fresh process, median of
seven, the committed 90-page corpus grown by suffixing slugs. Earlier editions of
this table carried much larger figures in the first column; those came from a
script that was never committed and cannot be reproduced, so they are superseded
rather than compared. Making the number reproducible was the point of writing
`speed.py`.

A warm search grows slowly in corpus size; what is left is interpreter startup and
one `stat()` pass over the store. The scan path stays usable to about 1000 pages,
which is what lets the index be a disposable cache instead of the store. The
~5000-page ceiling this document used to name is gone.

Six decisions, each bought by a probe rather than a preference:

- **No WAL.** A WAL database cannot be read from a read-only store at all, and WAL
  does not work over a network filesystem — which is exactly what
  `install.sh --store home` invites on a corporate or cloud-synced home directory.
  The default rollback journal reads fine in a `0555` directory.
- **The index lives outside the store**, in `$XDG_CACHE_HOME/pagelore/`,
  keyed by a hash of the store's resolved path. Inside the store it would be
  committed in `tracked` mode, and a store created before this feature existed
  would never receive a new `.gitignore` line. Resolving the path first means the
  `home` symlink and its target share one index instead of building two.
- **Freshness is `(mtime_ns, size, ino, ctime_ns)` per page, hashed, compared for
  equality.** Not an ordering — a clock that steps backwards makes a page look
  older, and "newer than the index" then serves stale content as fresh. Not
  `(mtime, size)` — `tar -xp`, `rsync -a` and `cp -p` restore mtimes, and only the
  inode and ctime catch an equal-sized rewrite underneath them. Hashed rather than
  stored, because parsing a per-page structure on every search cost a second at
  5000 pages for an equality test.
- **Rebuild whole, into a temporary file, moved into place.** A repair perpetuates
  whatever change it missed; a rebuild self-heals at the next mismatch, and a
  reader never sees a half-written index.
- **One builder, elected without waiting.** Twenty searches onto a cold index gave
  eleven `database is locked` failures; the winner of a non-blocking lock rebuilds
  and everyone else queries what already exists. A naive version of that had
  nineteen of twenty silently answer from an index still being written, so a
  coverage floor sends a caller to the markdown when the index does not yet hold
  most of the store.
- **The tokenizer is ours, and the index records its version.** FTS5's own
  tokenizers lose three behaviours with regression tests behind them: NFC
  normalisation (macOS NFD `ёлка` becomes unfindable), `casefold` (`STRASSE` /
  `straße`), and compound-identifier splitting. So `tokenize()` output is stored
  space-joined and FTS5 only splits on whitespace — which makes tokenisation part
  of the on-disk format, and a change to it without a rebuild would be zero recall
  with no error anywhere. The stamp forces the rebuild.

The two paths are different formulas, so the order of the low-scoring tail can
differ; measured, that is not a quality difference (+0.004 nDCG@10,
[-0.009, +0.018]). `--json` reports `served_by`, so a disagreement between two
agents in one fan-out is explainable rather than spooky.

## A result list always looks confident

The most useful thing the harness measured is a negative result. On 20 realistic
questions about the same project that **no page answers**, every method — this one,
FTS5, term counting, grep — returned hits for all 20. And the obvious fix does not
work: the top hit's score for a question the store cannot answer is
indistinguishable from one it can.

| median of the top hit | answerable | unanswerable |
|---|---|---|
| BM25F score | 9.93 | 8.73 |
| share of query words present | 0.58 | 0.56 |

A cutoff at any score that removes a meaningful share of the unanswerable set
removes more of the answerable one. Requiring 60% of the query's words to appear
kills 60% of the unanswerable queries and 36% of the correct answers with them.

The reason is structural, not a tuning failure: a question about a project you do
not have a page for still uses that project's vocabulary. Lexical scores measure
overlap, and the overlap is there either way.

So this is not fixed in the ranker, and the instruction to the agent carries it
instead: the list is not evidence that an answer exists, and each hit has to be
judged on what it says. Any system that returns a ranked list has this problem;
what is unusual here is only that it is measured.

A related but separate problem: a hit can be confident *and correct about the
past* — the page really did describe the code, once. `⚠ source changed` /
`⚠ source gone` (`freshness.py`, from git history) flags a page whose `sources`
moved on after the page did, or vanished outright. This is a marker, not a
ranking signal: a stale page is not demoted or dropped, because a rejected
alternative or a bug's cause is often still the useful part even after the code
around it changed shape. Judging a marked hit is still the agent's job, the same
as judging an unmarked one on the unanswerable set above.

## Parameters

`k1=1.2`, `b=0.75` — textbook. A cross-validated sweep found a different optimum
worth 0.017 nDCG@10, which does not justify carrying tuned constants that were
probably fitted to one corpus's quirks.

`W_TITLE=5.0` is the parameter that matters: raising the title weight from 0 to 5
is worth **+0.049 nDCG@10 [+0.025, +0.077]** on the corpus in `evals/`, an order of
magnitude more than k1 and b combined.

IDF is the Lucene form, `log(1 + (N − df + 0.5) / (df + 0.5))`. The classic
Robertson form goes negative once a term appears in more than half the corpus,
which actively penalises a page for containing the word "the".

Both fields are combined into one pseudo-frequency and saturated **once**
(that is what makes it BM25F rather than two BM25 scores added together —
the additive variant measured 0.024 nDCG@10 worse).

## Tokenization

`\w+` with the Unicode flag, over text normalised to **NFC** and folded with
`casefold()`. Both of those are load-bearing rather than cosmetic:

- `\w+` does not match combining marks, so without normalisation macOS's NFD
  `ёлка` tokenised as `['е', 'лка']` and matched nothing an editor writing NFC had
  produced. Recall across that boundary was zero, on the two most common
  diacritic letters in Russian — the language this store's bilingual claim is
  about.
- `casefold()` rather than `lower()` also folds `STRASSE` / `straße`.

The store is Cyrillic/Latin bilingual and tested that way. It is **not**
segmented: CJK returns one token per unbroken ideograph run, so retrieval for
Chinese, Japanese and Korean collapses to whole-phrase equality, and Thai
fragments meaninglessly. A tokenizer that fixes that needs a real segmenter,
which is not in the standard library; until then this is a known limitation
rather than a degraded mode.

Compound identifiers are indexed both whole and in pieces: `useAgentStream`
becomes `useagentstream`, `use`, `agent`, `stream`. Splitting happens before
folding, on `_` and at lower→upper boundaries only, so an all-caps `PTY`
survives intact. This inflates the index ~40% and measured **+0.0997** nDCG on
prose queries against **−0.0101** on identifier lookups — a good trade only
because identifier lookups were rare in the query log this was measured on (one
in every 154 queries recorded, across a longer window than the 110 graded for
ranking). On a corpus queried mostly by symbol name, re-measure before keeping it.

No stopword list (−0.0026 quality for −7% index size) and no minimum token length
(monotonically harmful: `pty`, `ws`, `id`, `v2`, `ru` all carry signal).

## Cost, and when to stop using this

Measured on one machine, on synthetic corpora built by replicating a real
491-page store, at roughly 5 KB per page. Both numbers matter: at the ~1.5 KB
pages a real store tends to produce these times are around 3x lower, and absolute
wall clock on another machine measures that machine. Treat the shape as the
result, not the constants.

| pages | build (whole index) | query |
|---|---|---|
| 491 | 0.29 s | 0.10 ms |
| 5 401 | 2.76 s | 0.19 ms |
| 50 082 | 25.4 s | 0.93 ms |
| 200 328 | 100.8 s | 3.37 ms |

Query time is never the problem; rebuilding is. **Around 5 000 pages** the
rebuild-everything-per-write model stops being free, and the right move is SQLite
FTS5, where an incremental edit is 0.21 ms flat regardless of corpus size and cold
open is 7 ms. If you do that, note that FTS5 joins bare query terms with implicit
AND — a two-word query then returns nothing. Terms must be joined with explicit
`OR`. This is a real bug that shipped in a production system and went unnoticed
for months.

A plain `grep -r` is faster in wall clock — it is not an *alternative*. Asked the
OR-of-terms question a real query needs, it returns an unranked list: on a
5 000-page store `grep -rilE` over three ordinary terms matched 98.7% of the
corpus. Ranking is what is being bought here, not speed. Where grep is genuinely
the better tool is a known literal — a slug, a file path, an error string — and
for that it should be used directly.
