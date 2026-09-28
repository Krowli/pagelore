# Measurements

Every number below is reproducible from this repository: the corpus, the
queries, the methods and the scorer are committed under `evals/`, and the
commands that produce each table are listed at the end. Intervals are 95%
bootstrap over queries; comparisons between methods are paired. One caveat
applies to all of it: the 90-page corpus and its 270 queries were written by a
language model about a fictional project, not harvested from a real store. The
`paraphrase` query type exists to fight the obvious bias — a query written from
a page tends to reuse its words — but it does not remove it.

## Retrieval quality

nDCG@10 on 270 known-item queries over 90 pages.

| method | nDCG@10 | vs shipped, paired |
|---|---|---|
| **shipped (FTS5 index)** | **0.649** [0.600, 0.691] | — |
| shipped fallback, in-process BM25F | 0.644 | +0.004 [−0.009, +0.018], not a difference |
| title weight set to 0 | 0.595 | +0.054 [+0.027, +0.081] |
| term-count scoring, the previous ranker | 0.432 | +0.216 [+0.164, +0.267] |
| `grep -rilE`, unranked | 0.113 | +0.535 [+0.480, +0.586] |

By query type, shipped: keywords 0.792, paraphrase 0.532, prose 0.622. On 12
ambiguous queries with several relevant pages, 0.462. The two shipped paths
are indistinguishable in quality, which is what makes the index safe to prefer
for speed.

The most useful negative result: on 20 realistic questions that **no page
answers**, every method returned hits for all 20, and the top hit's score is
no different — median 9.93 for an answerable question against 8.73 for an
unanswerable one. A score threshold that removes a meaningful share of the
unanswerable set removes more of the answerable one. So the instruction to the
agent carries this instead: a result list is not evidence that an answer
exists.

## Searching by file

50 source paths, one per page, each relevant to every page that cites it.

| the path given as | nDCG@10 | R@1 |
|---|---|---|
| query words | 0.545 [0.450, 0.638] | 0.380 |
| `--touching` | 0.986 [0.965, 1.000] | 0.960 |

Paired +0.441 [+0.349, +0.539]. The second row is near the ceiling by
construction; the first is what typing the path costs today, and words cannot
recover it because 77 of the 90 pages never name a source file in title or body.

## Embeddings, measured and refused

The hybrid of BM25F with a transformer embedding
(`paraphrase-multilingual-MiniLM-L12-v2`, reciprocal rank fusion) is better:
**+0.046 [+0.014, +0.075]**. It is refused on cost, not quality: the skill is a
script run afresh per search, so the model loads every time — about 1 000 ms
and 1.06 GB resident against 72 ms for the whole shipped search. Static
embeddings, the cheapest form of the idea, were then measured to the same bar:

| model | on disk | hybrid vs shipped | cold process to a vector | peak RSS |
|---|---|---|---|---|
| `potion-base-8M` | 30 MB | +0.031 [−0.002, +0.063] | 527 ms | 143 MB |
| `potion-retrieval-32M` | 129 MB | +0.029 [−0.002, +0.063] | 585 ms | 355 MB |
| `potion-multilingual-128M` | 512 MB | +0.012 [−0.019, +0.042] | 2 218 ms | 1 842 MB |
| shipped search, whole, cold | — | — | 86 ms | 26 MB |

No interval clears zero and the cheapest cold start is six times the shipped
search. Dense retrieval is also worst exactly where it is supposed to win: on
paraphrase queries the transformer scores 0.347 against the lexical ranker's
0.532.

## Against the closest competitor

Basic Memory 0.22.1 — markdown on disk plus a persistent hybrid index with
local embeddings and a link graph — on the same pages, queries and scorer:
overall 0.640 against 0.649, paired **+0.009 [−0.040, +0.058], not
significant**. Keywords 0.830 against 0.792 in its favour, paraphrase 0.481
against 0.532 in this project's favour. Latency is deliberately not compared:
Basic Memory is designed to run as a long-lived server.

## Does it help the agent

`evals/agent_loop.json`: the corpus written out as a real store, 18 questions
in three families put to an agent with the store, the same questions minus the
store-only ones to a control agent without it, graded against gold facts fixed
before the answers existed.

| | with the store | control, no store |
|---|---|---|
| answerable (8) — the answer is in exactly one page | 8 correct | not run |
| unanswerable (5) — no page answers it | 5 abstained | 5 abstained |
| superseded (5) — a decision was reversed; asks what holds *now* | 5 correct, 0 obsolete | 5 abstained |

Median effort: 2 searches and 2 pages read when the answer exists, 6 searches
before concluding it does not. One run, one grader, a fictional project the
model cannot confabulate about; read the unanswerable row as an upper bound.

## Does the agent use it unprompted

This is the measurement the product lives on, because nothing here fires by
itself: no hook, and since 0.4.0 no skill manifest for a harness to index either.
The only thing that makes an agent search before it answers is the instruction
block. `evals/acceptance.py` puts one question to a real session in a throwaway
project whose store holds the answer, and reads the store's log afterwards. A run
passes only if a search landed **before** the answer.

Fifteen sessions per arm, Claude Code 2.1.278, 2026-09-19, one question that never
says "why":

| how the agent learns the memory exists | searched before answering |
|---|---|
| the one `@path` line in `CLAUDE.md` | **15 / 15** |
| nothing at all — no line, no manifest, no tools | **0 / 15** |
| before 0.4.0: a registered skill directory, no instruction line | **15 / 15** |

The second row is a control that cannot pass, which is what makes the first row
mean anything. It is also the honest floor: install this and connect nothing, and
you have installed nothing. `lore doctor` therefore calls "installed but not
connected" a fault rather than a neutral state.

The third row is the one this repackage has to answer for, and it does not say
what was hoped. Up to 0.3.5 the program shipped as a skill directory a harness
could index, and that description alone made the agent search 15 times out of 15
with no instruction line anywhere. So dropping the packaging removed a fallback
that worked, for the specific user who installs and then connects nothing. The
recommended setup is 15/15 either way, which is why the trade was taken; what
pays for it is that `lore init` runs at install time and offers the line, `lore
doctor` calls an unconnected install a fault rather than a neutral state, and a
bare `lore` says so in one line. None of those existed when the skill directory
was doing the work.

One earlier single run covers a harness the 15-run arms do not: Codex CLI 0.153,
the block pasted into its rules, searched once and its answer followed the
`superseded by` marker to the reversal. Gemini, Cursor, Kimi, Copilot, OpenCode and
Pi are unmeasured until someone runs the same command there.

## MCP, measured — and offered as a choice

An MCP server here is a wrapper: it calls the same two functions, so retrieval
quality cannot differ. The claim to test was the other one — that an agent
reaches for the memory more reliably when the tools are in its tool list than
when an instruction file tells it about a command. `lore mcp` is that server,
stdlib only, and `evals/mcp_probe.py` is a wrapper over it so that
`evals/acceptance.py --pointer mcp|include|mcp+include` measures what ships.
Fifteen real sessions per arm on a task-shaped prompt that never says
"why", where the store holds the decision and its reversal.

| how the agent learns the memory exists | searched before answering |
|---|---|
| one `@path` line in the project's `CLAUDE.md` | 15 / 15 |
| MCP tools, Claude Code's default settings | **0 / 15** |
| MCP tools, `ENABLE_TOOL_SEARCH=false` | 15 / 15 |
| MCP tools plus the `@path` line | 15 / 15 |

The zero is not a model ignoring a tool it can see. Claude Code defers MCP tools
behind tool search by default, so they are not in the tool list at session start
at all, and the one advantage MCP was supposed to have does not exist out of the
box. With the deferral turned off it matches the instruction line exactly and
never beats it; added on top of it, it changes nothing.

For a while that kept MCP out of the package. It is shipped now, as `lore mcp`,
and the numbers are what changed their job: they are an argument for a default,
not for deciding on someone's behalf. So the wizard asks, the file is what Enter
gives you, and the measurement is printed on the question where the choice is
made.

Re-measured the day it shipped (2026-09-20, Claude Code 2.1.278, five sessions
per arm, the shipped server): MCP alone at default settings **3 / 5**, MCP alone
with `ENABLE_TOOL_SEARCH=false` 5 / 5, MCP plus the `@path` line 5 / 5. The
default arm is no longer zero and not yet reliable; the file is still the only
arm that has never missed. What would move the default is a harness that shows
MCP tools by default and has no instruction file worth writing into; the
acceptance run is there to re-measure rather than re-argue.

Then the server started saying when to use it (0.5.1): the `initialize` reply
carries `instructions` derived from the block's own paragraphs. Same acceptance
arm, MCP alone at default settings, Claude Code 2.1.281, ten sessions each on
2026-09-26: **4 / 10** without the instructions, **10 / 10** with them. One harness
version and ten runs per arm, so the default stays the file until a second harness
or the full three arms say the same.


## How agents use it: calls, repeats, `--touching`, per model

`evals/agent_eval.py`, Claude Code 2.1.283, 2026-09-28. Every session is a real
`claude -p` against a throwaway project built from the evaluation corpus, 10 runs
per cell, scored from the session's own tool calls and the store's log. Raw
records are committed in `evals/results/` and re-scored by `--summarize`.

Baseline (the 0.8.2 instruction text), 240 sessions, $24.12:

| | Opus 5.5 file | Opus 5.5 MCP | Sonnet 5 file | Sonnet 5 MCP |
|---|---|---|---|---|
| searched, any task | 60/60 | 60/60 | 60/60 | 45/60 |
| searched, edit-a-file task (C) | 10/10 | 10/10 | 10/10 | **4/10** |
| searched, fix-a-bug task (E) | 10/10 | 10/10 | 10/10 | **1/10** |
| `touching` on the edit (C) | 10/10 | 10/10 | 6/10 | 4/10 |
| correct, question in other words (F) | 10/10 | 10/10 | 10/10 | 10/10 |
| mean repeats, superseded question (D) | 0 | 0 | 0 | 1.0 |

The measured gap is not the query wording but the route: over MCP, Sonnet mostly
does not consult the memory when the task is "change this" rather than "answer
this"; with the instruction file it always does.

Guidance v1 ("every word in one query; search again only to ask something
different; `--touching` before a change", in a separate paragraph), 240 sessions:
Sonnet MCP searched on the edit task 10/10, but its paraphrase task over MCP fell to
4/10 correct (p≈0.011) and, with the instruction file, `touching` on the bugfix
fell to 3/10 (p≈0.003): the
"do not reword" sentence stopped Sonnet after a missed first search, and moving
the `--touching` sentence away from the command example made it stop using it.
Not shipped.

Guidance v2 (shipped in 0.8.3: "every word in one query", `--touching` kept
directly under the example, the "do not reword" sentence dropped), 80 sessions on
the Sonnet cells that v1 moved: touching on edits 21/40 → 28/40 (p=0.17), MCP
searched on the edit and bugfix tasks 5/20 → 9/20 (p=0.32), paraphrase task 10/10 → 9/10
(p=1.0). Every change points the right way and none is significant at this n;
the MCP edit-task gap remains the open problem. Repeats did not move in any run.

## Speed, and the cost of the gate

One search, end to end, as the command a user types: a fresh process, interpreter
startup included. `python3 evals/speed.py` produces this table, and `--pages`
changes the sizes. The corpus is the committed 90 pages grown by suffixing slugs.

| pages | warm, with the index | index refused | ratio |
|---|---|---|---|
| 90 | 52 ms | 76 ms | 1.5× |
| 1 000 | 69 ms | 341 ms | 4.9× |
| 5 000 | 139 ms | 1 507 ms | 10.8× |

The second column is not a hypothetical: it is what happens on a read-only
checkout, on a Python without `sqlite3`, and while a sibling process rebuilds the
index. That it stays usable to 1 000 pages is why the index is allowed to be a
disposable cache rather than the store.

Cold start by install route, same query, 90 pages:

| route | median |
|---|---|
| `lore`, installed by pipx | 52 ms |
| `python -m pagelore` | 52 ms |
| `lore`, installed by npm | 87 ms |

The npm route pays for a Node process that then spawns Python. It spawns the first
candidate interpreter with the real arguments rather than probing with a throwaway
`--version` first, because that probe would have added a second round trip to
every search.

Figures published before 0.4.0 came from an uncommitted script and are superseded,
not comparable: the measurement is in the repository now, which is the point.

The write gate was tuned to a real population: 104 of 495 pages in the corpus it
was designed against were stubs averaging 139 characters, and they took the top
two result slots. Before the per-page lock, concurrent writers on one slug —
ordinary with subagent fan-out — lost up to 16 of 20 sections while every command
exited 0.

## Reproduce

```bash
python3 evals/run.py --by-type                 # retrieval, touching, ambiguous, unanswerable, calibration
python3 evals/speed.py                         # the table above
python3 evals/dense_probe.py                   # needs fastembed; --static MODEL needs model2vec
python3 evals/compare_basic_memory.py          # needs basic-memory
python3 evals/acceptance.py --pointer include --agent '...'   # a real agent session
python3 evals/acceptance.py --pointer mcp --agent '...'       # the same session over MCP
pytest                                         # both retrieval paths, in CI on three operating systems
```

`evals/acceptance.py` needs `lore` on PATH and refuses to run without it: an agent
that tries to search and cannot would score the same as one that never tried. It
runs the first `lore` it finds, so point `PAGELORE_BIN=.venv/bin/lore` at the
editable install from [CONTRIBUTING](../CONTRIBUTING.md) — a stale released build already on PATH must not be the
one measured.

Every decision these numbers bought is also a page in this repository's own
`.memory/`, dated and sourced, including the ones that refused something.
