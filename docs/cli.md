# CLI reference

```
lore <command> [flags]        lore <command> --help for one command's flags
```

`pagelore` is the same program under a second name. Every command takes
`--version` and `-h/--help`. Commands that read or write a store take
`--store PATH`; without it the store is `$PAGELORE_DIR`, else the nearest
`.memory/` at or above the current directory (see [configuration](configuration.md)).

A bare `lore` prints the command list and exits 0, because an agent checking
whether the tool exists must not read a non-zero exit as a broken install; if
nothing is connected yet it adds one line saying so. On a real terminal a bare
`lore` opens the console (`lore dev`) instead. An unknown command exits 2 and
prints a `FIX:` line — `lore "why is auth server-side"` suggests
`lore search 'why is auth server-side'`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | done |
| 1 | `lore write` refused the page, or the store cannot be written (`REJECTED:` and `FIX:` on stderr); `lore doctor` found a failure |
| 2 | unknown command or bad usage; `show`, `edit`, `rm` given a slug that is not in the store (with a `FIX:` line); `edit` with no editor it can run |

## Reading

### `lore search`

```
lore search [-k K] [--store STORE] [--json] [--touching PATH] [query ...]
```

| Flag | |
|---|---|
| `query` | words, OR'd and ranked; give several |
| `-k K` | max results (default 10) |
| `--touching PATH` | put pages whose `sources` name this file, or anything under this directory, first, marked `▸ touches <path>`; repeatable; may replace the query. A file matches only itself, never its siblings |
| `--json` | machine-readable results |
| `--store STORE` | search this store |

One line per hit: `slug — title — what matched — [score] updated`. A page that
was replaced is marked `⚠ superseded by <slug>` and scored at half its rank; it
stays findable, because what was rejected and why is often the useful part.
Recency only breaks ties. A page under the 200-character floor is skipped and
named on stderr and in `--json`, so it can be rewritten; a page with no sources is
shown, marked `⚠ no sources`. Ranking: [retrieval](retrieval.md).

### `lore show <slug>`

```
lore show [--store STORE] slug
```

Prints one page, by the slug a search printed. If the page was superseded, stderr
says which page to read instead. stdout is always exactly the file on disk; stderr
also prints `linked from: a, b` — the other pages in the store whose `[[slug]]`
names this one, sorted, when there are any.

### `lore list`

```
lore list [--store STORE]
```

Every page, newest first, with kind and date; superseded pages are marked.

### `lore stats`

```
lore stats [--store STORE] [--since SINCE] [--json]
```

What the store has been doing, from its log: writes (new, merged, unchanged,
median size), refusals, searches and the ones that returned nothing, sessions
that searched and never wrote. `--since` takes an ISO date, e.g. `2026-08-09`.

```
2026-08-17T18:31:03 … 2026-09-16T23:35:03

writes       24   (19 new, 5 merged, 0 unchanged, median 1536 chars)
refused       0   (0% of write attempts)
searches     41   (7% returned nothing)
            miss: terminal pane rendering Zenith Tauri
sessions      1   (0 searched and never wrote, 4.00 writes per session)
```

## Writing

### `lore write`

```
lore write --slug SLUG --title TITLE [--kind KIND] [--source SOURCE]
           [--supersedes SLUG] [--body BODY] [--store STORE]
```

| Flag | |
|---|---|
| `--slug` | kebab-case identifier; the file is `.memory/<slug>.md` |
| `--title` | one line |
| `--kind` | one of `decision`, `bug`, `concept`, `howto` |
| `--source` | a file this page is about; repeatable; must exist |
| `--supersedes SLUG` | the page this one replaces; that page is stamped superseded |
| `--body` | the body, or `-` to read it from stdin |

```bash
lore write --slug webgl-context-loss --title "xterm WebGL context loss on display sleep" \
  --kind bug --source src/terminal/renderer.ts --body - <<'PMEOF'
## Cause

What a future agent could not reconstruct from the code...
PMEOF
```

The heredoc terminator is `PMEOF`, not `EOF`, so a page that documents heredocs
cannot end its own body early. Sources resolve against the project root (the
store's parent) first, then the current directory.

Re-running the same slug replaces same-header sections in place and appends new
ones, printing `replaced:` and `appended:` for each, so amendments are cheap and
safe. Concurrent writers on one slug are serialised by a per-page lock.

A re-run that would produce the exact same page — same title, kind, sources and
body — does not touch the file or its `updated` date: it prints `unchanged:
nothing to write` on stderr instead, still exits 0, and still prints the path.
Otherwise the same no-op write would look like a fresh edit later, to `git log`
and to anything that treats a recent `updated` as a sign the page was checked
against the code again.

**Writes are refused, not requested.** Asking an agent in prose to keep a
knowledge base tidy does not work — measured on a real corpus it produced 104
auto-generated stubs averaging 139 characters that took the top two result slots.
So `lore write` exits 1 and prints a `FIX:` line naming the next command when a
page has:

- no `--source`, or a `--source` path that does not exist;
- a title or body that looks like a committed credential (an AWS access key,
  a GitHub token — classic or fine-grained, an Anthropic or OpenAI API key, a
  Slack token, or a PEM private key header) — checked ahead of the length
  floor below, because a secret is the more urgent problem;
- a resulting page under 200 characters — measured on the page that will exist,
  so a short amendment to a substantial page is fine while a thin new page is not;
- an unknown `--kind`, or a slug that is not kebab-case;
- `--supersedes` naming a slug that is not in the store.

`--slug` and `--title` are required by the parser and produce its usage error; the
others are checked by the gate so that the refusal carries a `FIX:` line the agent
acts on. The refusal for a credential names its kind and location only — `title`,
or `body line N` counting the `--body` text on its own (not the title) — never
the matched value, since the refusal reason is written to the store's log.

A long random-looking string (base64/hex-like, 40+ characters, Shannon entropy
at or above 4.5 bits/character) does not refuse the write — it has false
positives on legitimate long tokens — but prints a warning to stderr after a
successful write, exit code still 0:

```
⚠ body line 12 looks like a credential (high-entropy string) — if it is one, remove it and rewrite the page
```

A `[[slug]]` link whose target has no page in the store is the same kind of
non-fatal problem — the write still succeeds, exit code 0, with one line per
distinct dangling target on stderr:

```
⚠ [[some-other-page]] names no page in this store — write it, or fix the slug
```

This is a warning rather than a refusal because an agent legitimately writes
page A linking to page B before B exists.

Page format: [page format](page-format.md).

### `lore edit <slug>`

```
lore edit [--store STORE] slug
```

Opens the page in `$VISUAL`, else `$EDITOR`, else `vi` (`notepad` on Windows), and
says so if the saved page fell under the floor search applies — the one way a hand
edit goes wrong silently.

### `lore rm <slug>`

```
lore rm [--store STORE] slug
```

Deletes one page and logs it, so `stats` still adds up.

## Setting up

### `lore init`

```
lore init [--agent {claude,gemini,codex,cursor}] [--scope {global,project}]
          [--via {file,mcp}] [--store {gitignored,tracked,home}]
          [--command COMMAND] [--yes] [--print] [--json]
```

| Flag | |
|---|---|
| `--agent` | connect this agent; repeatable; implies `--yes` |
| `--scope` | `global`: every project on this machine (default); `project`: only the repository you are standing in |
| `--via` | `file` (the default): the instruction file; `mcp`: a stdio server in the agent's tool list; repeatable |
| `--store` | where this project's pages live: `gitignored`, `tracked`, `home` |
| `--command` | the command name to write into the block (default: the name you ran) |
| `--yes` | take the answers as given, ask nothing |
| `--print` | print the line to add and exit |
| `--json` | print the result as one JSON document on stdout; the human messages go to stderr |

Each change is reported as one line — `wrote`, `updated`, `unchanged`,
`skipped`, `added`, `removed`, `run`, `paste`, `note`, `store`, `ignored` —
and under `--json` the same lines come back as `changes`:

```json
{
  "version": "0.5.0",
  "block": "/home/you/.pagelore/AGENT.md",
  "line": "@/home/you/.pagelore/AGENT.md",
  "scope": "project",
  "project": "/home/you/src/app",
  "agents": ["claude"],
  "via": ["file", "mcp"],
  "changes": [
    {"action": "wrote", "detail": "~/src/app/CLAUDE.md", "path": "/home/you/src/app/CLAUDE.md"},
    {"action": "wrote", "detail": "~/src/app/.mcp.json", "path": "/home/you/src/app/.mcp.json"},
    {"action": "note", "detail": "Claude Code asks once to approve the project's .mcp.json; run /mcp in a session to do it", "path": null}
  ]
}
```

With `--print --json` only `version`, `block` and `line` are printed. What each
answer writes: [connecting agents](agents.md).

### `lore doctor`

```
lore doctor [--json]
```

Checks the install and exits 1 if anything is broken in a way that produces no
error on its own. `--json` prints `{"version", "findings": [{"check", "ok",
"detail"}]}` where `ok` is `true`, `false`, or `null` (not applicable). Every
message: [troubleshooting](troubleshooting.md).

### `lore uninstall`

```
lore uninstall [--yes]
```

Takes out what `lore init` wrote — see
[installation](installation.md#uninstalling). `--yes` also removes pagelore's
own files in `~/.pagelore/` (the block and its version stamp), and the directory
once that leaves it empty; `--store home` project stores in it are kept and listed.

### `lore mcp`

```
lore mcp
```

Serves the memory over MCP on stdio. See [MCP](mcp.md).

### `lore version`

`lore version`, `lore --version` and `lore -V` print the version, the name it was
run as, the Python version and the directory the package runs from:

```
pagelore 0.5.0 (lore, python 3.13.1, /home/you/.local/pipx/venvs/pagelore/lib/python3.13/site-packages/pagelore)
```

### `lore dev`

```
lore dev [--sandbox] [--panes]
```

The same commands in a console: every line is one `lore` command run in its own
child process, so output and exit codes are exactly what an agent would see.
Internal words: `help`, `clear`, `panes`, `exit`.

- `--sandbox` runs against a throwaway store, project and `HOME`, discarded on
  exit, so `write`, `init` and `uninstall` can be rehearsed.
- `--panes` opens a full-screen view: an ask box, a transcript of the commands it
  runs (search hits as cards), `/` or ctrl+p for a command picker, `o` to open the
  top hit of the last search, ↑ for history, PgUp/PgDn to scroll, `q` back to the
  line editor. Commands that must own the terminal (`mcp`, the interactive `init`,
  `edit`) are refused from its field.

## Permissions

The whole surface is one program, so an agent can be granted exactly it: in
Claude Code the permission rule `Bash(lore:*)`, and the equivalent elsewhere.

## The log

Writes, refusals and queries are appended to `.memory/.log.jsonl`, each line
stamped with the Claude Code session id when the shell exports one
(`CLAUDE_CODE_SESSION_ID`). The store carries its own `.gitignore` for that file,
so it stays out of commits under every store mode — it holds every query anyone
typed. `lore stats` reads it: a refusal rate concentrated on one code usually
means a rule is wrong rather than the writer; searches that return nothing point
at a hole in the corpus or in ranking; sessions that searched and never wrote are
the write side's "did it happen".
