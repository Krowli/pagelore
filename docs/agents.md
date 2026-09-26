# Connecting agents

An agent uses the memory only if something tells it the memory exists. Measured on
Claude Code, an agent with the instruction line searched before answering 15 times
out of 15; with nothing connected, never. So connecting is the step that matters.

There are two routes, and you can use both:

- **The instruction file** (the default). One line — or, where a client cannot
  include a file, the block's text — in the file the agent reads every turn. It
  tells the agent to run `lore search` before stating anything about the project
  and `lore write` after a decision or a non-obvious fix.
- **An MCP server.** `lore mcp` puts `memory_search` and `memory_write` in the
  agent's tool list. See [MCP](mcp.md).

You can set this up for every agent on the machine, for one project, or for one
specific agent. The client configuration below was checked against each client's
own documentation (links under [Sources](#sources)); if your version differs, its
docs win.

## `lore init`

```bash
lore init
```

writes the block to `~/.pagelore/AGENT.md` and asks four questions. Arrows
move, space ticks, enter confirms, escape skips; digits work too, and without a
terminal (a pipe, CI) the questions become a numbered prompt.

1. **Where this applies** — this repository only, or every project on this
   machine. Asked only inside a git repository.
2. **Which agents** — Claude Code, Gemini CLI, Codex CLI, Cursor. Each row names
   the file it will write. **The default connects nothing.**
3. **How the agent reaches it** — instruction file, MCP server, or both. Enter
   keeps the file, the measured default; the measurement is printed on the
   question.
4. **Where this project's pages live** — private and gitignored (the default),
   committed with the repository, or outside it behind a `.memory/` symlink into
   `~/.pagelore/<project>/`.

It previews the exact change and asks before writing. Running it again replaces
its own fenced block instead of adding a second one, and reports `unchanged` for a
file that already says the same thing.

The same answers as flags — flags are the confirmation, so this works in a script:

```bash
lore init --agent claude --agent codex --yes
lore init --agent claude --scope project --store tracked --yes
lore init --agent cursor --via mcp --scope project --yes
lore init --agent claude --via file --via mcp --json     # result as JSON on stdout
lore init --print                                        # just print the line to add
```

With no terminal and no flags it asks nothing, writes only the block, prints the
manual instructions and exits 0. All flags: [CLI reference](cli.md#lore-init).

## Why a line, not a copy

The line points at a file rather than carrying the text, because a transcription
is a fork: the next release changes the block, every pasted copy stays as it was,
and nothing says so. `~/.pagelore/AGENT.md` is refreshed by every `lore`
invocation (about 50 µs against a 50 ms search), so an upgrade reaches every agent
that includes it. Where a client has no include syntax the text is pasted instead;
the block carries a version stamp in an HTML comment and `lore doctor` reports a
pasted copy that has gone stale. Claude Code strips block-level HTML comments
before injecting a `CLAUDE.md`, so the stamp costs the agent nothing.

## 1. Every project, every agent

```bash
lore init --agent claude --agent gemini --agent codex --agent cursor --yes
```

| Agent | File it reads every turn | What `lore init` puts there |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `@<home>/.pagelore/AGENT.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` | `@<home>/.pagelore/AGENT.md` |
| Codex CLI | `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`) | the block's text, pasted |
| Cursor | no file — User Rules live in **Customize → Rules** | nothing; init tells you to paste the block there |
| Anything else | whatever it reads every turn | either, if it expands `@path` |

Everything goes inside a fenced block
(`<!-- pagelore: managed by `lore init` … -->` … `<!-- pagelore: end -->`) that
`lore uninstall` removes without touching what you wrote around it.

- **Claude Code** expands `@path` imports, relative or absolute, up to four hops
  deep, and loads the imports of a user-level `CLAUDE.md` without an approval
  dialog.
- **Gemini CLI** takes the same `@file` syntax, relative or absolute.
- **Codex** documents no import syntax, so it gets the text. It reads the global
  file from `$CODEX_HOME` (default `~/.codex`), `AGENTS.override.md` first if one
  exists — `lore init` writes `AGENTS.md`, so an override file would hide it.
- **Cursor**'s User Rules are a text field. Paste the contents of
  `~/.pagelore/AGENT.md` there (`lore init --print` shows the path), or use
  the MCP route, which does have a global file.

The MCP route for every project — see [MCP](mcp.md#registering-it) for the
per-client detail:

```bash
lore init --agent claude --agent gemini --agent codex --agent cursor --via mcp --yes
```

## 2. One project

```bash
lore init --agent claude --agent codex --scope project --yes
```

`--scope project` writes into the repository you are standing in instead of your
home directory:

| Agent | Project file | Mechanism |
|---|---|---|
| Claude Code | `CLAUDE.md` | `@` line |
| Gemini CLI | `GEMINI.md` | `@` line |
| Codex CLI and Cursor | `AGENTS.md` — read by both | the block's text, pasted |

Choosing Codex or Cursor here writes the same `AGENTS.md`; choosing both writes
it once. Outside a git repository `--scope project` says so and falls back to the
global files.

Worth knowing per client:

- **Claude Code** treats an import in a project `CLAUDE.md` that resolves outside
  the project — as `@~/.pagelore/AGENT.md` does — as an *external import*:
  the first time, it shows an approval dialog, and if you decline the import stays
  disabled. Approve it once. Claude Code reads a project `AGENTS.md` by itself only
  when there is no `CLAUDE.md` in the working directory or above.
- **Cursor** applies `AGENTS.md` from the project root and from subdirectories.
- **Codex** walks from the repository root down to the working directory,
  reading `AGENTS.override.md` or `AGENTS.md` in each.

A project file overrides nothing by itself; put a narrower instruction there if a
project needs one.

The pages themselves, per project (`--store`):

| `--store` | Where | Notes |
|---|---|---|
| `gitignored` (default) | `.memory/` | created by the first write, which also gitignores it |
| `tracked` | `.memory/` with a `.tracked` marker | committed and reviewed in pull requests — do not write secrets |
| `home` | `~/.pagelore/<project>/`, reached through a `.memory/` symlink | the symlink is added to `.gitignore` |

## 3. One specific agent

### A Claude Code subagent

A subagent file limits its tools with `tools:`. MCP tools are named
`mcp__<server>__<tool>`, and `mcp__<server>` allows every tool of a server. With
the server registered as `pagelore` (`lore init --via mcp`):

`.claude/agents/archivist.md` (or `~/.claude/agents/` for every project):

```markdown
---
name: archivist
description: Answers "why is it like this" questions about this project from its recorded decisions, and records new ones. Use before changing an unfamiliar subsystem.
tools: Read, Grep, Glob, mcp__pagelore__memory_search, mcp__pagelore__memory_write
---

Search project memory with memory_search before stating anything about this
project. Give several words; they are OR'd and ranked. A hit marked
"superseded by <slug>" was replaced — read the replacement first. If nothing
relevant comes back, say so rather than guessing.

After an architectural decision, a non-obvious bugfix or a contract change, record
it with memory_write: kind is decision, bug, concept or howto; sources are files
that exist. A refusal says why and what to do instead — follow it.
```

Without MCP, give the subagent `Bash` and the same instructions with `lore search`
and `lore write` — the text of `~/.pagelore/AGENT.md` is the tested wording.
Claude Code's permission rule `Bash(lore:*)` grants exactly this program.

### A Codex profile

A Codex profile is a separate file, `~/.codex/<name>.config.toml`, with top-level
keys, selected with `codex --profile <name>`. To point one profile at a
particular store through the shell it gives the agent:

```toml
# ~/.codex/archivist.config.toml
[shell_environment_policy]
set = { PAGELORE_DIR = "/path/to/project/.memory" }
```

```bash
codex --profile archivist
```

The instructions still come from `AGENTS.md` (global or project) or the prompt.

### Any agent, by environment

Every command honours `PAGELORE_DIR`, so an agent started with it set
searches and writes that store wherever it runs:

```bash
PAGELORE_DIR=/path/to/project/.memory my-agent --task "…"
```

The MCP server honours it too, and otherwise uses `CLAUDE_PROJECT_DIR` or walks up
from its working directory. See [configuration](configuration.md).

## Compatibility

| Agent | How it learns the memory exists | Verified |
|---|---|---|
| Claude Code | `@~/.pagelore/AGENT.md` in `CLAUDE.md` | yes, 15 of 15 acceptance sessions |
| Codex CLI | the block pasted into `AGENTS.md` | yes, one acceptance run on Codex CLI 0.153 |
| Gemini CLI | `@~/.pagelore/AGENT.md` in `GEMINI.md` | per vendor docs |
| Cursor | the block in the project `AGENTS.md` or User Rules; or MCP | per vendor docs |
| Anything else | either, in whatever it reads every turn | n/a |
| Any of them, over MCP | `lore mcp` in its tool list, registered by `lore init --via mcp` | Claude Code: alone at default settings 0 of 15, later 3 of 5; every time with `ENABLE_TOOL_SEARCH=false` or with the file |

Gemini, Cursor, Kimi, Copilot, OpenCode and Pi are unmeasured until someone runs
`evals/acceptance.py` there — see [measurements](measurements.md).

## Sources

- Claude Code memory, imports and AGENTS.md: https://code.claude.com/docs/en/memory
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code permission rules (`Bash(lore:*)`): https://code.claude.com/docs/en/permissions
- Gemini CLI `GEMINI.md`: https://geminicli.com/docs/cli/gemini-md/
- Gemini CLI MCP servers: https://geminicli.com/docs/tools/mcp-server/
- Codex AGENTS.md: https://learn.chatgpt.com/docs/agent-configuration/agents-md
- Codex MCP: https://learn.chatgpt.com/docs/extend/mcp
- Codex profiles and `shell_environment_policy`: https://learn.chatgpt.com/docs/config-file/config-advanced
- Cursor MCP: https://cursor.com/docs/context/mcp
- Cursor rules and AGENTS.md: https://cursor.com/docs/context/rules
