---
slug: mcp-offered-as-a-choice
title: "MCP ships as a choice the wizard offers; the measurement stays on the question"
kind: decision
created: 2026-09-20
updated: 2026-11-04
checked: 2026-11-04T15:26:30+00:00
supersedes:
  - mcp-measured-and-refused
sources:
  - evals/mcp_probe.py
  - src/pagelore/init.py
  - src/pagelore/mcp.py
---

## What changed, and what did not

[[mcp-measured-and-refused]] measured MCP against one `@path` line and kept the
server out of the package: 0/15 searches on Claude Code's defaults, where the
harness defers MCP tools behind its tool search; 15/15 with the deferral off or
with the file as well — equal to the file, never better. The numbers stand and
are not re-argued here.

What changed is whose decision it is. The owner's call, 2026-09-20: the person
connecting an agent chooses how it reaches the memory. So `lore init` asks a
fourth question — instruction file, MCP server, or both — and `--via file|mcp` is
the same answer for a script. Enter keeps the file: the numbers are an argument
for a default, not for deciding on someone's behalf. They are printed on the
question itself, because it is only a choice if what was measured is in front of
the person as they make it; and when MCP alone is picked on Claude Code, the
wizard says so once more after writing.

The wizard now asks four questions, not the three [[wizard-asks-with-arrows-and-scope]]
records. The "no server" promise in [[scripts-carry-the-contract-not-hooks]]
holds for the default: nothing in the product depends on `lore mcp` running, and
it exists in a harness's config only where a person ticked it.

## One implementation, measured where it ships

The probe moved into the package as `pagelore.mcp` and `evals/mcp_probe.py` is a
wrapper over it, so `evals/acceptance.py --pointer mcp` keeps working unchanged
and measures the shipped code. Tool names and descriptions are the measured text;
changing them means running the acceptance arms again.

## How the server finds the store

Claude Code promises a stdio server no working directory; it puts the project
root in `CLAUDE_PROJECT_DIR` instead. So the store is `PAGELORE_DIR`, then
`find_store(CLAUDE_PROJECT_DIR)`, then the cwd walk every command uses. The write
goes through `write.main` with `--store` passed explicitly, which also makes
`--source` paths resolve against the project root (`resolve_source` tries the
store's parent first). Gemini spawns the server without a `cwd` and so inherits
its own; Codex was not probed — `lore mcp` prints the store it serves on stderr
so a wrong one is diagnosable from the harness's logs.

## Why two mechanisms write the registration

The same shape as include/paste on the file route. Claude Code's project
`.mcp.json` and Gemini's `settings.json` are documented as plain JSON that people
edit by hand, so the entry is merged into them in place and everything else is
kept; a file that is not plain JSON is left alone and the command is printed.
`~/.claude.json` is Claude Code's own state file and hand edits are not
documented; Codex's `config.toml` is TOML, which the standard library cannot
write at all and cannot read before 3.11. Those two go through the harness's
own `mcp add` when the harness is on PATH, and the line is printed when it is
not. Uninstall mirrors it: drop the JSON entry (and delete a `.mcp.json` this
program emptied, never Gemini's file), run or print `mcp remove` for the rest.

The command written is the bare name — `lore mcp` — never a path into one
person's home, because `.mcp.json` is meant to be committed and an absolute path
breaks it for the next clone. `lore doctor` checks the name is on PATH and runs
that very binary through a handshake, so an old install earlier on PATH than the
new one fails there and says which one.

`~/.claude.json` is read at the top level only. It also nests local-scope
servers under each project's path; those are not ours — this program never
writes local scope — and a recursive walk reported another project's entry as
this one's and would have sent `uninstall` after it.

## What would move the default

A harness that shows MCP tools by default and has no instruction file worth
writing into. Re-run the three acceptance arms there before changing what Enter
gives.

## Re-measured after shipping

2026-09-20, Claude Code 2.1.278, the shipped server through `evals/mcp_probe.py`,
five runs per arm after one trial run of each (trial in brackets). Agent command:
`claude --setting-sources project --no-session-persistence --mcp-config
{project}/.mcp.json --strict-mcp-config --allowedTools
mcp__project-memory__memory_search mcp__project-memory__memory_write Read -p
{prompt}`; the `mcp+include` arm also allowed `Bash(lore:*)` and `Bash(cat:*)`.

| arm | searched before answering |
|---|---|
| MCP alone, default settings | 3/5 (trial: 1/1) — was 0/15 on 2026-09-19 |
| MCP alone, `ENABLE_TOOL_SEARCH=false` | 5/5 (trial: 1/1) |
| MCP plus the `@path` line | 5/5 (trial: 1/1) |

The default arm is no longer zero and not yet reliable: two of the five sessions
answered without a search. Not investigated why the number moved — the harness
version differs from the September 19 run, and `--strict-mcp-config` with two
tools may keep the deferrable definitions under the 10 % threshold that turns
tool search on. What the wizard says was updated to carry both numbers; the
default stays the file, which is still the only arm that has never missed.
