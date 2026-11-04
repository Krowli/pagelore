---
slug: pages-confirmed-against-code
title: "lore confirm: a checked page is marked again only by a later source commit"
kind: decision
created: 2026-11-04
updated: 2026-11-04
sources:
  - evals/agent_eval.py
  - src/pagelore/confirm.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/freshness.py
  - src/pagelore/mcp.py
---

## Context

`⚠ source changed` ([[sources-drift-marked-from-git]]) fires on any commit to a cited
file. On 2026-11-04 it sat on 46 of this repository's 48 pages, so it no longer told an
agent which page to distrust, and the only way to clear it was to change a page that
was still right.

## Decision

`lore confirm <slug>` stamps `checked:` (UTC, seconds, `+00:00`) into the frontmatter
and logs a `confirm` event. `freshness.drift` uses that time in place of the page
file's own clock when it is newer, so only a source committed after the check marks
the page again. A page with a gone source is refused (`FIX: lore edit`), because a
check cannot vouch for a file that is not there. `updated` is untouched.

The clock is wall time against a source's commit time — the comparison `drift`
already made for an uncommitted page's mtime. Rewriting the page alone would not
work: a committed page's clock is its last commit, which an uncommitted confirm
does not move.

## Rejected

- Recording HEAD's sha and resolving its commit time at search time: a second git
  call per search, and an unreachable sha after a rebase silently undoes the check.
- Background LLM consolidation, which is how Graphiti, Supermemory and Cognee
  handle staleness: it needs a model and a key, and the agent already in the
  session can check the page for free, visibly in git.

An MCP `memory_confirm` tool was deferred here at first, because the tool list is
measured text ([[mcp-offered-as-a-choice]]). It shipped once the run below
measured it.

## First audit, 2026-11-04

The command shipped, and then all 41 current pages carrying the marker were checked against the code:

- 28 held as written and were confirmed.
- 13 needed a correction first, and were then confirmed.

The 13 corrections:

- the `PROJECT_MEMORY_*` environment names, now `PAGELORE_*`;
- the pre-0.4.0 script and skill names (`memory_search.py`, `SKILL.md`, `USE.md`);
- the block's home directory, now `~/.pagelore`;
- drifted character counts;
- descriptions of the panes screen that predated its reshape.

So the marker was carrying real signal, about one page in three, but it was buried under the other two. After the audit, no current page carries `⚠ source changed`. The six superseded pages keep theirs on purpose: `⚠ superseded by` already tells a reader to go elsewhere.

## Measured, 2026-11-04

Setup: `evals/agent_eval.py` task G — two pages cite one file. After a later
commit one of them is still true (clipboard reads are refused) and one is now
false (the write cap went from 100 000 to 1 000 000 bytes). Claude Code 2.1.318
with Opus 5.5, and Codex CLI 0.166 through `acceptance.py --task G`, 10 sessions
per cell, paired.

| route | true page confirmed | false page fixed |
|---|---|---|
| file, without the AGENT.md sentence | 0/10 | 2/10 |
| file, with it | 10/10 | 10/10 |
| Codex, without the sentence | 0/10 | 0/10 |
| Codex, with it | 10/10 | 10/10 |
| MCP, two tools | 0/10 | 0/10 |
| MCP, `memory_confirm` + search description | 5/10 | 7/10 |

- No session confirmed the false page without fixing it.
- Every arm answered correctly, because the agent reads the code either way. The
  sentence changes what the next agent finds in the store.
- Cost: about one extra turn, and $0.02 per session.
- The search rate on task A did not move.
- The MCP gap is the one MCP already has for search: 7 of 10 sessions searched at
  all.
- Details and raw records: `docs/measurements.md`, `evals/results/`.
