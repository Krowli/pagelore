# Configuration

pagelore has no configuration file. What it reads is below; everything else is a
command-line flag.

## Environment variables

### Set by you

| Variable | Read by | Effect |
|---|---|---|
| `PAGELORE_DIR` | every command, `lore mcp` | The store to use, instead of the nearest `.memory/` at or above the current directory. `~` is expanded. |
| `PAGELORE_HOME` | every command | Where the instruction block lives, instead of `~/.pagelore` (the block is `AGENT.md` inside it). `lore init` writes the include line with this path; `lore uninstall --yes` removes the block and stamp in it, and the directory once empty. |
| `PAGELORE_NO_REFRESH` | every command | Any non-empty value stops the automatic refresh of `AGENT.md` after each command. Used by the test suite; a person rarely needs it. |
| `PAGELORE_NO_FTS5` | `lore search` | Any non-empty value refuses the SQLite FTS5 index, so search reads and ranks the pages directly — the same path a Python without FTS5 takes. |
| `PAGELORE_PYTHON` | the npm shim only | The Python interpreter to run. Exclusive: if it does not work, `lore` fails and says so rather than trying another. |
| `PROJECT_MEMORY_*` | as above | The pre-0.6.0 names of the five variables above. Still read in 0.6.x when the `PAGELORE_*` name is unset, with a one-line warning on stderr; removed in 0.7.0. |
| `PAGELORE_NO_LOG` | every write and search | Any non-empty value turns off `.memory/.log.jsonl` entirely — `log_event` writes nothing. Set by `evals/speed.py` on the processes it spawns, so a benchmark run never lands in a real log. |
| `CODEX_HOME` | `init`, `uninstall`, `doctor` | Codex's home directory (default `~/.codex`): the global `AGENTS.md` and `config.toml` are read and written there, as Codex itself does. |
| `VISUAL`, `EDITOR` | `lore edit` | The editor, in that order; the fallback is `vi` (`notepad` on Windows). |
| `NO_COLOR`, `TERM=dumb` | `lore init` | Turn off colour in the wizard. A pipe never gets colour. |
| `XDG_CACHE_HOME` | `lore search` | The search index lives in `$XDG_CACHE_HOME/pagelore/`, else `~/.cache/pagelore/`. |

### Set by an agent's harness

| Variable | Read by | Effect |
|---|---|---|
| `CLAUDE_PROJECT_DIR` | `lore mcp` | When `PAGELORE_DIR` is not set, the store is looked up from this directory rather than the server's working directory. |
| `CLAUDE_CODE_SESSION_ID` | writes and searches | Stamped into each line of `.memory/.log.jsonl`, so `lore stats` can count sessions. Absent, the line carries no session. |

### Set by pagelore itself

| Variable | Effect |
|---|---|
| `PAGELORE_INVOKED_AS` | The npm shim passes the name it was run as (`lore` or `pagelore`), so messages and the block written by `init` name the command that will be there tomorrow. |
| `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE` | The npm shim puts its vendored source on `PYTHONPATH` and turns off `.pyc` writes, since a global npm prefix is often not writable. |

`PAGELORE_BIN` is read only by `evals/acceptance.py`, to choose which `lore` a
measurement runs — see [measurements](measurements.md#reproduce).

## Files

| Path | Written by | What it is |
|---|---|---|
| `.memory/*.md` | `lore write` | The pages — the source of truth. Format: [page format](page-format.md). |
| `.memory/.log.jsonl` | every write and search | The log `lore stats` reads. Kept out of git by the store's own `.gitignore`. |
| `.memory/.tracked` | `lore init --store tracked` | Marks a store that is committed on purpose; the first write then does not gitignore it. |
| `.gitignore` (project) | the first write in a new store; `init --store home` | Gets `.memory/` added, unless the store is tracked. |
| `~/.pagelore/AGENT.md` | `lore init`, refreshed by every command | The instruction block agents include. Refreshed only if the directory already exists — a command never creates it. |
| `~/.pagelore/.version` | `lore init` | The version and command name the block was written for. |
| `~/.pagelore/<project>/` | `lore init --store home` | A project's pages, outside the repository, reached through a `.memory/` symlink. |
| `~/.project-memory` | the 0.6.0 upgrade | A link to `~/.pagelore`, left where the directory used to be so that `--store home` symlinks made before 0.6.0 still resolve. `lore uninstall --yes` removes it when it points at `~/.pagelore` and removes that directory. |
| `~/.cache/pagelore/` | `lore search` | The FTS5 index, keyed by the store's resolved path. A cache: delete it whenever you like; it rebuilds. |

The files `lore init` writes into each agent's configuration are listed in
[connecting agents](agents.md) and [MCP](mcp.md#registering-it).
