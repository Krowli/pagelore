# pagelore

[![CI](https://github.com/Krowli/pagelore/actions/workflows/test.yml/badge.svg)](https://github.com/Krowli/pagelore/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/pagelore.svg)](https://pypi.org/project/pagelore/)
[![npm version](https://img.shields.io/npm/v/pagelore.svg)](https://www.npmjs.com/package/pagelore)
[![Python versions](https://img.shields.io/pypi/pyversions/pagelore.svg)](https://pypi.org/project/pagelore/)
[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange.svg)](https://github.com/Krowli/pagelore/blob/main/LICENSE)

**Durable project memory for AI coding agents — Claude Code, Codex, Cursor, Gemini
CLI.** Decisions, contracts and bug post-mortems live as **markdown pages in your
repository**, searched with BM25F from a command line or an MCP server, and every
write is validated before it lands. No server, no database to run, no API key, no
hooks; the runtime is the Python 3.9+ standard library.

**Works with:** Claude Code · Codex CLI · Cursor · Gemini CLI · anything that can
run a shell command or an MCP stdio server.

## Why

Agents re-derive the same context every session and confidently restate decisions
that were reversed months ago. A memory store fixes that only if it is cheap to
write, cheap to read, and survives switching tools. Plain markdown in git
satisfies all three: the store is a `.memory/` directory of `.md` files —
greppable, diffable, reviewable in a pull request, readable by any agent or
person.

- **Search that ranks.** BM25F over title and body; a SQLite FTS5 index kept as a
  disposable cache outside the store, and an in-process ranker when the index
  cannot be used. [Measured](https://github.com/Krowli/pagelore/blob/main/docs/measurements.md) against grep, embeddings and the
  closest competitor.
- **Writes are refused, not requested.** A page with no sources, a source that
  does not exist, or too little body is rejected with a `FIX:` line the agent acts
  on.
- **Reversals stay honest.** `--supersedes` stamps the old page, halves its score
  and marks it `⚠ superseded by <slug>` in every result.
- **One instruction line connects an agent.** `lore init` writes it (or registers
  the MCP server) and `lore doctor` catches the setups that fail silently.

## Install

```bash
pipx install pagelore && lore init && lore doctor     # or: npm install -g pagelore
```

`lore init` shows the exact change and asks before writing; its default connects
nothing. `lore doctor` says what is connected and what is broken. Other routes
(pip, uv, from source), upgrading and removal: [installation](https://github.com/Krowli/pagelore/blob/main/docs/installation.md).

## Quick start

Connect Claude Code in this repository only, with the instruction file:

```bash
lore init --agent claude --scope project --yes
```

Your agent now searches before it answers and writes after meaningful work. The
same commands by hand:

```bash
lore search "terminal freeze webgl context lost"     # ranked hits: slug — title — what matched
lore search --touching src/terminal/renderer.ts      # pages written against this file, first
lore show webgl-context-loss                         # one page, by the slug a search printed
lore write --slug webgl-context-loss --title "xterm WebGL context loss on display sleep" \
  --kind bug --source src/terminal/renderer.ts --body - <<'PMEOF'
## Cause

The WebGL renderer loses its context when the display sleeps; what a future
agent could not reconstruct from the code goes here.
PMEOF
lore list                                            # every page, newest first
lore stats                                           # writes, refusals, searches that found nothing
```

Or as MCP tools, `memory_search` and `memory_write`, in the agent's tool list:

```bash
lore init --agent claude --via mcp --scope project --yes   # writes .mcp.json
```

## How it works

```
  agent (Claude Code, Codex, Cursor, Gemini CLI, …)
     │ reads one @-line or pasted block every turn          ~/.pagelore/AGENT.md
     │
     ├── lore search / show / write   (shell)  ─┐
     └── lore mcp  memory_search / memory_write ─┤  same functions, same gate
                                                 ▼
                          .memory/*.md   ← the source of truth, in your repo
                          FTS5 index     ← a cache in ~/.cache, rebuilt on demand
```

The instruction block lives in one file, `~/.pagelore/AGENT.md`, refreshed
by every `lore` command; each agent's configuration carries one line pointing at
it, so an upgrade reaches every agent without editing anything. Measured on
Claude Code: with the line the agent searched before answering 15 times out of
15, without it never.

## Documentation

- [Installation](https://github.com/Krowli/pagelore/blob/main/docs/installation.md) — pipx, pip, uv, npm, from source; upgrading, uninstalling, 0.3.x
- [Connecting agents](https://github.com/Krowli/pagelore/blob/main/docs/agents.md) — every agent at once, one project, one specific agent
- [MCP server](https://github.com/Krowli/pagelore/blob/main/docs/mcp.md) — `lore mcp`, its two tools, per-client registration
- [CLI reference](https://github.com/Krowli/pagelore/blob/main/docs/cli.md) — every command and flag, exit codes, the write gate, the log
- [Configuration](https://github.com/Krowli/pagelore/blob/main/docs/configuration.md) — environment variables and files
- [Troubleshooting](https://github.com/Krowli/pagelore/blob/main/docs/troubleshooting.md) — what each `lore doctor` line means
- [FAQ](https://github.com/Krowli/pagelore/blob/main/docs/faq.md)
- [Page format](https://github.com/Krowli/pagelore/blob/main/docs/page-format.md) · [Retrieval](https://github.com/Krowli/pagelore/blob/main/docs/retrieval.md) · [Measurements](https://github.com/Krowli/pagelore/blob/main/docs/measurements.md)
- [Contributing](https://github.com/Krowli/pagelore/blob/main/CONTRIBUTING.md) · [Security](https://github.com/Krowli/pagelore/blob/main/SECURITY.md) · [Changelog](https://github.com/Krowli/pagelore/blob/main/CHANGELOG.md)

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) — see
[LICENSE](https://github.com/Krowli/pagelore/blob/main/LICENSE). Free for personal, research,
educational and other noncommercial use. Commercial use — selling it, or building it into a paid
product or service — needs a separate license: write to lionmause999@gmail.com.

Versions up to and including 0.7.0 were released under MIT and stay under MIT.
