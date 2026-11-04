---
slug: snippet-included-not-copied
title: "The instruction block ships inside the skill and is included, not copied"
kind: decision
created: 2026-09-18
updated: 2026-11-04
checked: 2026-11-04T15:30:10+00:00
sources:
  - README.md
  - evals/acceptance.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/init.py
---

## Context

With the hooks gone ([[scripts-carry-the-contract-not-hooks]]), two things make
an agent use the memory: the skill's `description`, which the harness shows by
itself, and the instruction block the agent reads every turn. The block was the
repository root's `AGENTS.md`, and the README told the user to transcribe it
into their own configuration.

Two faults in that. `install.sh` copies `skills/project-memory/` and nothing
else, so the file the README named never reached the user's disk at all — the
instruction was "open this page on GitHub and retype it". And a transcription
is a fork: the next release changes the block, every pasted copy stays as it
was, and nothing anywhere says so.

## Decision

The block lives at `skills/project-memory/USE.md`, inside the directory every
install mode copies. Where a harness can include a file by path, the README
gives one line instead of forty:

    @~/.agents/skills/project-memory/USE.md

Claude Code expands `@path`, home-relative paths included, four hops deep, and
loads a user-scope file's imports without an approval dialog. Gemini CLI takes
the same syntax in `GEMINI.md` — its own extension ships two such lines. Codex
documents no import syntax and Cursor's User Rules is a text field, so those
two keep the transcription, and the block carries a version stamp in an HTML
comment so a stale copy is visible to whoever pasted it. Claude Code strips
block-level comments before injection, so the stamp costs the agent nothing.

The repository root's `AGENTS.md` is the same file byte for byte, and a test
fails if the two drift. That is the cheapest thing that stops the copy nobody
opens from becoming the one that is wrong.

## Measured

`evals/acceptance.py` grew `--pointer none|paste|include`, because "the README
says to add this line" is a claim about a mechanism and the project does not
ship those unmeasured. Run 2026-09-18, Claude Code, **no skill registered with
the harness at all**, the project's `CLAUDE.md` containing only the import
line: one search before answering, and the answer followed the `superseded by`
marker to the reversal. The import alone is enough.

## Rejected

Pointing the include at `SKILL.md`, which also ships: at 161 lines it is the
full contract, and a global `CLAUDE.md` is paid for on every turn of every
session in every project. The block is 34 lines and is the part that has to be
resident. Generating the file at install time with the resolved absolute path:
plugin installs never run `install.sh`, so it would be correct for one install
mode and absent for the others.

## Since 0.4.0

The decision holds: the block is one file that agents include by path, not a copy. Its location moved when 0.4.0 replaced the copied skill directory with an installed command ([[installed-command-not-copied-directory]]).

These no longer exist:

- `skills/project-memory/USE.md`
- `SKILL.md`
- `install.sh` copying a skill tree

How it works now:

- **The text.** The canonical text is `src/pagelore/data/AGENT.md`.
- **On disk.** `lore init` writes it to `~/.pagelore/AGENT.md` and rewrites it whenever the installed version changes.
- **Including it.** For Claude Code and Gemini CLI, `lore init` adds one `@` line with that file's path to `~/.claude/CLAUDE.md` and `~/.gemini/GEMINI.md`. Codex's `AGENTS.md` has no import syntax, so there it pastes the block.
- **This repository.** Its own `AGENTS.md` is still the rendered block, byte for byte, and `tests/test_instruction_block.py` fails if they differ.
- **Measuring.** `evals/acceptance.py --pointer none|paste|include` still measures the routes.
