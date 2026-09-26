# MCP server

`lore mcp` serves the same memory as two MCP tools over stdio. The tools call the
functions the commands call — same ranking, same write gate, same `FIX:` lines —
so retrieval quality cannot differ between the two routes. It is standard library
only, like the rest of the program.

## The tools

| Tool | Inputs | What it does |
|---|---|---|
| `memory_search` | `query` (string; several words, OR'd and ranked), `touching` (array of file or directory paths; pages written against them first), `limit` (integer, default 10) | Same as `lore search` |
| `memory_write` | `slug`, `title`, `kind` (`decision` \| `bug` \| `concept` \| `howto`), `sources` (array of paths that exist), `body` (markdown, `## ` sections) — all required; `supersedes` (array of slugs) | Same as `lore write`; a refusal comes back as an error result carrying the reason and the `FIX:` line |

The tool descriptions carry the same trigger as the instruction block — search
before stating anything about the project, write after a decision or a
non-obvious fix — because the two routes were compared on that promise.

Protocol details: JSON-RPC 2.0, one message per line on stdin and stdout,
protocol version `2025-06-18`, server name `pagelore`. stdout carries
JSON-RPC and nothing else; the server prints one line on stderr naming the store
it serves.

## What the server tells the agent on connect

The `initialize` reply carries `instructions`, the field the MCP specification
describes as a hint to the model that a client may add to its system prompt. It is
not written separately: it is the paragraphs of the instruction block
(`src/pagelore/data/AGENT.md`) marked `<!-- mcp -->`, with the two that introduce a
command naming `memory_search` and `memory_write` instead. So an agent that has
only the server — no instruction file — is told when to search and when to write,
in the words the file uses, and the two cannot drift. About 1.2k characters;
`python3 evals/mcp_probe.py --handshake` prints what a client receives.

## Which store it serves

A stdio server is promised no working directory, so `lore mcp` resolves the store
once at start, in this order:

1. `PAGELORE_DIR`, if set;
2. the project Claude Code names in `CLAUDE_PROJECT_DIR` — the nearest `.memory/`
   at or above it;
3. the nearest `.memory/` at or above the directory it was started in.

A store that does not exist yet is fine; the first write creates it.

## Registering it

`lore init --via mcp` does this for you (`--scope project` for the project files).
The entry always names the bare command — `lore mcp` — never a path into one
person's home, so a committed `.mcp.json` works for the next person to clone;
`lore doctor` checks that the name is on PATH.

| Client | Scope | Where | How `lore init` does it |
|---|---|---|---|
| Claude Code | project | `.mcp.json` in the repository, meant to be committed | merges the entry into the JSON |
| Claude Code | every project | `~/.claude.json` | runs `claude mcp add --transport stdio --scope user pagelore -- lore mcp`, or prints it when `claude` is not on PATH |
| Gemini CLI | project / every project | `.gemini/settings.json` / `~/.gemini/settings.json` | merges the entry into the JSON |
| Codex CLI | every project | `$CODEX_HOME/config.toml` (default `~/.codex/config.toml`) | runs `codex mcp add pagelore -- lore mcp`, or prints it |
| Cursor | project / every project | `.cursor/mcp.json` / `~/.cursor/mcp.json` | merges the entry into the JSON |

`lore init` merges into a JSON file only when it is plain JSON, keeping every
other key; a file with comments in it is left alone and the command to run is
printed instead. For Codex, `lore init` registers globally whatever the scope.
Codex also reads a project `.codex/config.toml` in trusted projects; add the
server there yourself if you want it per project.

The entries, by hand:

```jsonc
// .mcp.json (Claude Code) — also the shape for .cursor/mcp.json and ~/.cursor/mcp.json
{
  "mcpServers": {
    "pagelore": { "type": "stdio", "command": "lore", "args": ["mcp"] }
  }
}
```

```jsonc
// .gemini/settings.json or ~/.gemini/settings.json — Gemini has no "type" for stdio
{
  "mcpServers": {
    "pagelore": { "command": "lore", "args": ["mcp"] }
  }
}
```

```toml
# ~/.codex/config.toml
[mcp_servers.pagelore]
command = "lore"
args = ["mcp"]
```

or the clients' own commands:

```bash
claude mcp add --transport stdio --scope user pagelore -- lore mcp
gemini mcp add --scope user pagelore lore mcp
codex mcp add pagelore -- lore mcp
```

Claude Code asks once, in an interactive session, before it uses a project's
`.mcp.json` servers; approve it there (`/mcp` shows the state).

In tool lists the tools appear under the client's own prefix — in Claude Code
`mcp__pagelore__memory_search` and `mcp__pagelore__memory_write`, in
Gemini CLI `mcp_pagelore_memory_search` and so on.

Before 0.6.0 the server was registered as `project-memory`. `lore init --via mcp`
replaces an entry under that name when it has exactly the shape `init` wrote,
`lore uninstall` removes both names, and `lore doctor` names an old entry that is
still there. A permission rule or agent definition that lists
`mcp__project-memory__…` needs the new prefix.

## File, MCP, or both

Measured on Claude Code, fifteen sessions per arm on a task-shaped prompt
(details in [measurements](measurements.md#mcp-measured--and-offered-as-a-choice)):

| How the agent learns the memory exists | Searched before answering |
|---|---|
| one `@path` line in the project's `CLAUDE.md` | 15 / 15 |
| MCP tools, Claude Code's default settings | 0 / 15 (re-measured later: 3 / 5, then 4 / 10) |
| the same, with the server's `instructions` (0.5.1) | 10 / 10 |
| MCP tools, `ENABLE_TOOL_SEARCH=false` | 15 / 15 |
| MCP tools plus the `@path` line | 15 / 15 |

Claude Code defers MCP tools behind tool search by default, which is why MCP alone
did worse there. That is why the file is the default and the wizard asks rather
than deciding: pick MCP where a client shows its tools up front, or add it on top
of the file.

## Taking it out

`lore uninstall` removes the entry from every place `lore init` can put it — see
[installation](installation.md#uninstalling).

## Sources

- MCP lifecycle, `initialize`: https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Gemini CLI MCP servers: https://geminicli.com/docs/tools/mcp-server/
- Codex MCP: https://learn.chatgpt.com/docs/extend/mcp
- Cursor MCP: https://cursor.com/docs/context/mcp
