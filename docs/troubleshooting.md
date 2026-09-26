# Troubleshooting

Start with:

```bash
lore doctor            # or: lore doctor --json
```

Every failure it reports is silent by nature — the agent does not error, it just
stops using the memory — which is why the command exists. It exits 1 when any line
is `FAIL`. `ok` is fine, `--` means not applicable (nothing to check there).

## What each line means

### The block

| Line | Meaning | Fix |
|---|---|---|
| `ok  ~/.pagelore/AGENT.md` | The instruction block exists. | — |
| `FAIL  … AGENT.md is missing — run lore init` | Nothing for an `@` line to include. | `lore init` |

### Instruction files (`agent:<name>` and `project:<file>`)

Global files are checked for Claude Code, Gemini CLI and Codex; inside a git
repository, the project's `CLAUDE.md`, `GEMINI.md` and `AGENTS.md` are checked too
when they carry the managed block.

| Line | Meaning | Fix |
|---|---|---|
| `--  Claude Code: no ~/.claude/CLAUDE.md` | That agent has no global instruction file. | Only a problem if you meant to connect it. |
| `--  Claude Code: not connected (…)` | The file exists but carries no pagelore block. | `lore init --agent claude` |
| `--  Cursor: global rules live in Customize → Rules, not a file; not checked` | Cursor's User Rules cannot be read from disk. | — |
| `ok  Claude Code: includes …/AGENT.md` | The `@` line points at a file that exists. | — |
| `FAIL  …: includes … — that file is MISSING, the agent silently loads nothing` | A dangling include: the agent loads nothing and says nothing. | `lore init` |
| `ok  Codex CLI: pasted copy of 0.5.0` | A pasted block from this version. | — |
| `FAIL  …: pasted copy of 0.4.1 — STALE, this install is 0.5.0` | Codex and Cursor carry a copy no upgrade can reach. | `lore init` again for that agent; paste again into Cursor's User Rules |
| `ok  …: includes ~/.project-memory/AGENT.md — the pre-0.6.0 path; …` | Works through the link the 0.6.0 upgrade left behind. | `lore init` for that agent points it at `~/.pagelore` |
| `FAIL  …: carries a pre-0.4.0 block — run lore init to replace it` | A block from the old shell installer. | `lore init` — it replaces the old marker |

### MCP registrations (`mcp:<name>`)

Checked in: the project's `.mcp.json`, then `~/.claude.json` (top-level
`mcpServers` only) for Claude Code; `.gemini/settings.json` then
`~/.gemini/settings.json`; `.cursor/mcp.json` then `~/.cursor/mcp.json`; and
`$CODEX_HOME/config.toml`.

| Line | Meaning | Fix |
|---|---|---|
| `--  Gemini CLI: not registered as an MCP server` | No entry. | Only a problem if you meant to use MCP. |
| `ok  Claude Code: MCP server in … → lore mcp` | Registered, and the command is on PATH. | — |
| `ok  …: MCP server in … (command not readable)` | Registered; the command could not be read out of the file. | — |
| `FAIL  …: MCP server in … → lore mcp — but lore is not on PATH; the harness cannot start it` | The client will fail to start the server, quietly. | Put the install on PATH (`pipx ensurepath`), or re-register with `lore init --command pagelore …` if that is the name you have |
| `ok  … mcp answers tools/list with memory_search, memory_write` | The server the config names starts and lists both tools. | — |
| `FAIL  Claude Code: MCP server still registered as project-memory in …` | The pre-0.6.0 server name. It still starts, but an agent given it beside `pagelore` sees every tool twice. | `lore init --via mcp` replaces an entry it wrote; `lore uninstall` removes it; an entry you edited, rename by hand |
| `FAIL  … mcp did not answer tools/list: …` | The binary the config names is not a working server — often an old install earlier on PATH. | Check `lore --version`; remove the older install |

### The rest

| Line | Meaning | Fix |
|---|---|---|
| `ok  N agent(s) connected` | At least one instruction file or MCP registration is live. | — |
| `FAIL  0 agent(s) connected — nothing tells any agent the memory exists` | Installed but not connected. Measured, an agent in that state never searches. | `lore init` |
| `ok  …/.memory: N page(s)` / `… does not exist yet; the first write creates it` | Where this directory's store is. | — |
| `ok  /…/bin/lore (this install: …)` | The `lore` on PATH is the one running. | — |
| `FAIL  neither lore nor pagelore is on PATH` | Agents cannot run it. | `pipx ensurepath`, or add npm's global bin to PATH |
| `FAIL  … is a different install (…), not this one (…)` | Two installs; a client starts the first one on PATH. | Uninstall one, or put this one first on PATH |
| `FAIL  … does not answer --version` | An old build on PATH. | Upgrade or remove it |
| `FAIL  both ~/.project-memory and ~/.pagelore exist; …` | The 0.6.0 move was refused because the new directory already existed; nothing is merged automatically. | Move what you still need (a `--store home` project's pages) into `~/.pagelore`, then delete `~/.project-memory` |
| `FAIL  ~/.project-memory is the pre-0.6.0 location; …` | Not moved yet — only with `PAGELORE_NO_REFRESH` set. | `lore init` |
| `FAIL  ~/.agents/skills/project-memory is left over from the skill-directory layout and is safe to delete` | 0.3.x leftovers. | Delete it; see [upgrading from 0.3.x](installation.md#upgrading-from-03x) |

## Other problems

**`lore: command not found`.** The program is not on this shell's PATH. With pipx,
run `pipx ensurepath` and open a new shell. Do not write pages by hand instead: a
hand-written page is skipped by search while it is under 200 characters and
flagged while it has no sources.

**The npm `lore` says it cannot find Python.** It lists every interpreter it tried.
Install Python 3.9+, or set `PAGELORE_PYTHON` to one you have; if that
variable is set, nothing else is tried.

**The agent does not search.** Run `lore doctor`. Then start a *new* agent
session — instruction files are read at session start. On Claude Code with a
project `CLAUDE.md`, approve the external-import dialog for
`~/.pagelore/AGENT.md` the first time; if it was declined, the import stays
disabled. With MCP only, Claude Code defers MCP tools behind tool search by
default; add the instruction file as well (see [MCP](mcp.md#file-mcp-or-both)).

**The project `.mcp.json` server does not start in Claude Code.** Claude Code
asks once, in an interactive session, before it uses a project's servers. Approve
it; `/mcp` shows the state.

**`lore init` skipped a JSON file.** It was not plain JSON (comments, trailing
commas), so it was left alone and the line to add was printed.

**`lore init` printed `run  claude mcp add …` or `codex mcp add …`.** That client is
not on PATH here, so pagelore did not edit its file by hand; run the printed
command where the client is installed.

**A write was refused.** The `REJECTED:` line says why and the `FIX:` line says
what to run; see [the write gate](cli.md#lore-write).

**Search is slow or the index looks wrong.** The index is a cache in
`~/.cache/pagelore/`; delete it and it rebuilds. `PAGELORE_NO_FTS5=1`
bypasses it entirely.

**A page landed in the wrong store.** `lore mcp` prints the store it serves on
stderr at start. Set `PAGELORE_DIR` to be explicit; see
[configuration](configuration.md).
