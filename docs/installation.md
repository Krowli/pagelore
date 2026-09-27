# Installation

pagelore is one program with two names: `lore`, the documented one, and
`pagelore`, for a machine where something else already owns `lore`. Every message
names whichever one you ran, and `lore init` writes that name into the block your
agent reads.

Requires **Python 3.9 or newer** — what a stock macOS ships. The runtime has no
dependencies outside the standard library.

## From PyPI

```bash
pipx install pagelore              # recommended: an isolated environment, `lore` on PATH
pip install --user pagelore        # also works
uv tool install pagelore           # with uv
uvx --from pagelore lore search …  # run once without installing
```

## From npm

```bash
npm install -g pagelore
```

The npm package is a shim, not a port: it finds a Python interpreter and hands it
the Python source vendored into the tarball at pack time. It runs no `pip` and no
`postinstall` script, so `--ignore-scripts` and a corporate registry mirror both
work. It tries `python3` then `python` (on Windows `py -3`, `python`, `python3`);
to pin one, set `PAGELORE_PYTHON` — see [configuration](configuration.md).
If you already have `pipx`, `pipx install pagelore` is the same program and needs
no Node.

## From source

```bash
git clone https://github.com/Krowli/pagelore && cd pagelore
make dev                  # .venv with an editable install, pytest and ruff
.venv/bin/lore --version
```

In a clone with nothing installed, `python3 -m pagelore …` works from the
repository root with `src/` on `sys.path`. See [CONTRIBUTING](../CONTRIBUTING.md).

## Connect an agent, then check

```bash
lore init
lore doctor
```

`lore init` writes the instruction block to `~/.pagelore/AGENT.md` and then
asks four questions — where it applies, which agents, how they reach it (file or
MCP), and where this project's pages live. The details, and the flags that answer
them in a script, are in [connecting agents](agents.md). `lore doctor` checks the
result; its messages are explained in [troubleshooting](troubleshooting.md).

Installing without connecting anything installs nothing useful: measured, an agent
with no instruction line and no MCP server never searched. A bare `lore` says so
in one line, and `lore doctor` calls it a failure.

## Which install is running

```bash
lore --version        # or: lore version
```

prints the version, the name it was run as, the Python, and the directory the
package runs from. If you installed through both pipx and npm you have two `lore`
on PATH; `lore doctor` fails when the one on PATH is not the one running it.

## Upgrading

```bash
pipx upgrade pagelore          # or: npm update -g pagelore, uv tool upgrade pagelore
```

The instruction block is refreshed by the next `lore` command you or your agent
runs, so there is nothing to re-copy. A **pasted** copy — Codex's `AGENTS.md`, a
project `AGENTS.md`, Cursor's User Rules — is the exception: run `lore init`
again, and `lore doctor` reports a stale one.

## Uninstalling

In this order:

```bash
lore uninstall                 # take the block and the MCP entries back out
pipx uninstall pagelore        # or: npm uninstall -g pagelore, uv tool uninstall pagelore
```

`pipx uninstall` cannot run pagelore's code, so it would leave the fenced block
behind as an `@include` pointing at a file nothing will recreate — and an agent
that cannot load an `@path` does not error, it just stops searching.

`lore uninstall` removes only what `lore init` wrote, plus what a pre-0.4.0 copied
install left behind:

- the fenced block in `~/.claude/CLAUDE.md`, `~/.gemini/GEMINI.md` and
  `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`), and in the `CLAUDE.md`,
  `GEMINI.md` and `AGENTS.md` of the project you are in and of every project
  `lore init --scope project` connected (recorded in `~/.pagelore/projects`);
  everything you wrote around the fence stays;
- the `pagelore` MCP entry — and a pre-0.6.0 `project-memory` one — in each such
  project's `.mcp.json` (deleted if it is
  then empty), `.gemini/settings.json` and `.cursor/mcp.json`, and in
  `~/.gemini/settings.json` and `~/.cursor/mcp.json` (those files are never
  deleted);
- for `~/.claude.json` and Codex's `config.toml` it runs `claude mcp remove
  --scope user pagelore` / `codex mcp remove pagelore` (and the same for
  `project-memory`) when that program is on PATH, and prints the command when it
  is not.
- a pre-0.4.0 `project-memory` skill copy — `~/.agents/skills/project-memory`,
  a project's `.agents/skills/project-memory`, and the `.claude/skills/` links to
  them — but only a directory that carries the old `scripts/memory_search.py`;
- the hooks that copy wrote into `~/.claude/settings.json` or a project's
  `.claude/settings.json` (the ones tagged `_managed_id: project-memory-…`); every
  other hook and setting in those files stays.

`lore uninstall --yes` also removes pagelore's own files in `~/.pagelore/` — the
block `AGENT.md` and its `.version` stamp — and then the directory itself if that
leaves it empty. A `lore init --store home` project keeps its pages in that same
directory (`~/.pagelore/<project>/`), so any such store, and anything else in there
pagelore did not write, is kept and listed; the directory stays. The link a 0.6.0
upgrade left at `~/.project-memory` is removed only when it points at
`~/.pagelore` and that directory is gone. **Your pages are never touched**; delete
a `.memory/` directory, or what is left of `~/.pagelore/`, yourself if you mean to.

## Upgrading to 0.6.0: one name

Before 0.6.0 the program was `pagelore` but everything around it was still called
`project-memory`. 0.6.0 renames the rest; nothing needs doing by hand.

- **`~/.project-memory` becomes `~/.pagelore`.** The first `lore` command after
  the upgrade (or `lore init`) moves it in one rename and leaves a link at the old
  path, so a `lore init --store home` project whose `.memory` points into the old
  directory keeps working. The `@` line `lore init` wrote into `~/.claude/CLAUDE.md`,
  `~/.gemini/GEMINI.md` and the current project's `CLAUDE.md`/`GEMINI.md` is
  repointed inside the managed block only. If both directories already exist,
  nothing is merged and `lore doctor` says so. Set `PAGELORE_HOME` and nothing moves.
- **`PROJECT_MEMORY_*` variables become `PAGELORE_*`** (`DIR`, `HOME`,
  `NO_REFRESH`, `NO_FTS5`, `PYTHON`). The old names are still read in 0.6.x, with a
  one-line warning on stderr; 0.7.0 stops reading them.
- **The MCP server is registered as `pagelore`.** `lore init --via mcp` replaces a
  `project-memory` entry that has exactly the shape it wrote; one you edited is left
  alone, and `lore doctor` names it. Tool names are unchanged, so permission rules
  and agent definitions change only in the server part:
  `mcp__project-memory__memory_search` → `mcp__pagelore__memory_search`.
- **The search index moves to `~/.cache/pagelore/`.** It rebuilds on the next
  search; `~/.cache/project-memory/` can be deleted.
- **The repository is `github.com/Krowli/pagelore`.** Old links redirect.

## Upgrading from 0.3.x

0.3.x installed a skill directory and wrote a line pointing into it. That
directory is gone, so do this once, in this order:

```bash
sh install.sh --uninstall      # or re-run the curl one-liner; it now only uninstalls
pipx install pagelore
lore init
```

`lore init` also recognises and replaces the old marker, so if you forget the
first step you get one block rather than two. A plugin or extension install is
separate:

```
Claude Code   /plugin uninstall project-memory
Gemini CLI    gemini extensions uninstall project-memory
Codex, Cursor, Kimi   remove the directory you pointed them at
```

`lore doctor` names a leftover `~/.agents/skills/project-memory` directory.

## Platforms

Tested in CI on Ubuntu, macOS and Windows against Python 3.11 and 3.13, and on 3.9
on Linux and Intel macOS, on both retrieval paths (FTS5 index and the in-process
ranker). The 3.9 floor is declared once and enforced everywhere it matters:
`requires-python` stops pip, and the npm shim treats exit 69 from an older
interpreter as "try the next one".
