---
slug: pages-confirmed-against-code
title: "lore confirm: a checked page is marked again only by a later source commit"
kind: decision
created: 2026-11-04
updated: 2026-11-04
sources:
  - src/pagelore/confirm.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/freshness.py
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
- An MCP `memory_confirm` tool, for now: the tool list is measured text
  ([[mcp-offered-as-a-choice]]), so it waits for a measured run.
- Background LLM consolidation, which is how Graphiti, Supermemory and Cognee
  handle staleness: it needs a model and a key, and the agent already in the
  session can check the page for free, visibly in git.

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
