---
slug: agent-query-guidance-measured
title: "Agent guidance measured on real Claude Code sessions: one query, --touching; 'do not reword' refused"
kind: decision
created: 2026-09-28
updated: 2026-09-28
sources:
  - evals/agent_eval.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/mcp.py
---

## Question

Real logs showed agents asking the memory the same question several times in
reworded queries, and recorded sessions barely using `--touching`. Would the
instruction text fix that, and does it change whether agents search at all?

## Measurement

`evals/agent_eval.py` runs real `claude -p` sessions (Claude Code 2.1.283)
against a throwaway project built from the corpus. The grid is two models
(claude-opus-5-5, claude-sonnet-5) × two routes (the `@path` instruction file,
MCP) × six tasks (why, unanswerable, edit a file, superseded, fix a bug,
question in other words) × 10 runs. Each session is scored from its own tool
calls and the store log. Raw records are in `evals/results/`.

Baseline, the 0.8.2 text, 240 sessions:

- Opus searched in 120/120 sessions.
- Sonnet searched 60/60 with the file, but only 45/60 over MCP: 4/10 on the
  edit task and 1/10 on the bugfix task.
- Repeats were rare. They showed up mainly for Sonnet over MCP (a mean of 1.0
  on the superseded question).

## Decision

- **v1 was refused.** It added "search again only to ask something different,
  not to reword" and moved the `--touching` sentence into a separate paragraph
  (240 sessions). It lifted Sonnet over MCP on the edit task to 10/10 searched,
  but it did damage in two places:
  - the paraphrase task over MCP fell to 4/10 correct (p≈0.011), because the
    sentence stops Sonnet after a missed first search;
  - `touching` with the instruction file on the bugfix fell from 10/10 to 3/10
    (p≈0.003), because the sentence no longer sat under the command example.
- **v2 shipped in 0.8.3.** It keeps "every word in one query", keeps
  `--touching` directly under the example, drops the reword sentence, and adds
  one paragraph about passing `touching` before a change. That paragraph is
  marked `<!-- mcp -->` in the source block so the MCP server's `initialize`
  result includes it, but `render()` only strips the marker line, not the
  paragraph, so it also renders into the instruction file — both routes see
  it, not MCP alone. It was measured on the 80 Sonnet cells v1 moved:
  - touching on edits: 21/40 → 28/40 (p=0.17);
  - searched over MCP on the edit and bugfix tasks: 5/20 → 9/20 (p=0.32);
  - paraphrase task: 10/10 → 9/10.

  Everything moves in the right direction, nothing is significant at n=10, and
  nothing regressed.

## What is still open

Over MCP, Sonnet often does not consult the memory at all when the task is
"change this" rather than "answer this". That is a route problem, not a
wording one, and no wording measured so far fixes it. Wording also did not
change repeats in any run.

Where a sentence sits matters as much as what it says: the same
`--touching` advice measured 10/10 directly under the example and 3/10 one
paragraph below it.
