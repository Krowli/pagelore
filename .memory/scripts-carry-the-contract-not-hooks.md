---
slug: scripts-carry-the-contract-not-hooks
title: "The contract rides in the scripts and the skill text, not in any agent's hooks"
kind: decision
created: 2026-09-16
updated: 2026-11-04
checked: 2026-11-04T15:30:10+00:00
supersedes:
  - session-hook-not-an-invitation
  - stop-hook-reminds-once
sources:
  - docs/research/superpowers-portability.md
  - evals/acceptance.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/search.py
  - src/pagelore/stats.py
---

## Context

Three Claude Code hooks carried three guarantees: SessionStart announced the
memory, PreToolUse denied a hand-written page, Stop reminded a session that
changed files and wrote nothing. Every one of them existed on one harness.
Codex, Gemini, Cursor, Kimi, Copilot, OpenCode and Pi got the manifests and
the prose, and the README admitted nobody had watched those paths run. The
owner's requirement is that the skill work the same on every agent, so a
mechanism one harness has is not a mechanism.

The reference point is obra/superpowers, the most widely installed skills
library, surveyed by primary sources in `docs/research/superpowers-portability.md`.
Its portability comes from one skill tree in harness-neutral vocabulary, a
per-harness adapter that only registers `skills/` and injects one bootstrap
text at session start, and — where a harness has no injection point (Codex,
Devin, Grok, Droid) — nothing at all: the skill's own `description` in the
harness's skill index is the trigger. It uses no PreToolUse and no Stop hook
on any harness; compliance is prose plus an acceptance test per harness, which
its porting guide calls "the only guarantee". Codex's session-start hook was
removed in 6.1.0 because the native skill index worked better.

## Decision

`hooks/` is gone, along with its registration in `install.sh` and the Cursor
manifest. Each guarantee moved to a place that exists on every harness:

- **Announcing the memory** is the skill `description` in SKILL.md, the
  manifest-declared context files (GEMINI.md, Kimi `sessionStart.skill`) and
  the AGENTS.md snippet — the superpowers no-hook path, already in place.
- **The write gate runs on read.** `memory_search.py` skips a page under
  MIN_BODY that matched the query and names it on stderr and in `--json`; a
  page with no sources is shown, marked `⚠ no sources`. MIN_BODY moved to
  memory_lib so writer and reader share one floor. Search runs wherever the
  skill is installed, so the check holds wherever a page can arrive.
- **Writing after work** is a finishing rule in SKILL.md and the pointer
  files, and the number that tells whether it is followed — sessions that
  searched and never wrote — is counted by `memory_stats.py` from the session
  id the scripts stamp into the log, with no hook collecting it.

## Rejected

An MCP server as the universal transport: its tool list is visible in every
session on every MCP-capable agent, which is a hook-free announcement, but it
breaks the "no server" promise and was not asked for. Keeping the hooks as an
optional layer: the owner asked for one path, and a guarantee that holds on one
harness and not another is the confusion this decision removes. Checking
source existence on read: a page whose source moved is still the page to read,
and hiding it would be a reconcile pass nobody asked for.

## What this costs

The session-start text is no longer guaranteed to be in context on Claude
Code; the skill description and the pointer files are. Superpowers' evidence
is that this works on Codex, Devin and Grok and is unverified elsewhere, and
its documented failure modes apply here too: no trigger guarantee on
index-only harnesses, loss after compaction where nothing re-injects. The
acceptance check in `evals/acceptance.py` is the only guarantee, exactly as
superpowers says, and it has to be run per harness.

## Measured

`evals/acceptance.py`, 2026-09-16, no hook anywhere, no pointer file in the
project, the 90-page corpus as the store, one question only the store answers.
Claude Code (skill loaded with `--plugin-dir`, user settings excluded): two
searches before answering, first query `GPU rendering disabled default
terminal`, answer named the canvas decision, 19 s. Codex CLI 0.153 (skill via
`.agents/skills`, `--ignore-user-config --ignore-rules`): one search, query
`terminal gpu webgl default decision`, answer named the canvas decision and
followed the `superseded by` marker to the reversal, 24 s. One run each, one
question; this says the description-only path fires on these two harnesses
today, not how often. Gemini, Cursor, Kimi, Copilot, OpenCode and Pi are
unmeasured until someone runs the same command there.

## Since 0.4.0

The decision holds: no hook on any harness, the contract carried in text and in
the program. The names above come from the copied-skill layout that 0.4.0
replaced with one installed command ([[installed-command-not-copied-directory]]).

| Then | Now |
|---|---|
| `memory_search.py` | `lore search` (`src/pagelore/search.py`). It still skips a matching page under `MIN_BODY` on read and shows one with no sources marked `⚠ no sources`. |
| `memory_lib` | `src/pagelore/lib.py` |
| `memory_stats.py` | `lore stats` (`src/pagelore/stats.py`). It still counts sessions that searched and never wrote, from the session id stamped into the log. |
| `SKILL.md` and the skill `description` | gone; see below |

The memory is now announced in two ways:

- The instruction block `src/pagelore/data/AGENT.md`. `lore init` installs it as `~/.pagelore/AGENT.md` and includes or pastes it into each agent's instruction file.
- The `instructions` field of `lore mcp`, where a person chose MCP ([[mcp-sends-instructions-on-connect]]).
