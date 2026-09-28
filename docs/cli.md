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

A hit whose `sources` have moved on since the page was written is marked, from
git history: `⚠ source changed: a.py, b.py` when a source's last commit is newer
than the page's own, `⚠ source gone: c.py` when a source no longer exists.
`--json` carries the same two lists as `stale_sources` and `gone_sources` on
every hit, always present, possibly empty. Neither marker changes ranking or
appears at all outside a git work tree — no repository, no `git` binary, a
timed-out call — because `gone` cannot be decided reliably without the project
root, and that root is only known here because git named it.

`changed` compares a source's last commit with the page's own last commit, or,
for a page that is never committed — the default gitignored store, a `home`
store, a page not committed yet — with the page file's modification time. A
clone never creates such a file, so its mtime is the time it was last written.

### `lore show <slug>`

```
lore show [--store STORE] slug
```

Prints one page, by the slug a search printed. If the page was superseded, stderr
says which page to read instead. stdout is always exactly the file on disk; stderr
also prints `linked from: a, b` — the other pages in the store whose `[[slug]]`
names this one, sorted, when there are any — and, same as search,
`⚠ source changed: a.py` / `⚠ source gone: b.py` when git history says a source
moved on after the page (nothing outside a git work tree).

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
median size), refusals, searches and the ones that returned nothing, which
route each search came in on, how often a search re-returned a top page
another search had already returned within the last two minutes,
`--touching` searches and the ones whose path found no page, sessions that
searched and never wrote. `--since` takes an ISO date, e.g. `2026-08-09`.

The `touching` line reads its miss count against how many of those searches
were run after the `touched` field existed to measure them (`measured`), not
against the total — a log spanning the field's introduction otherwise reads as
a much lower miss rate than the measurable slice actually had.

The `via` line under `searches` only appears once some record in the log
carries the field (it shipped after `search` itself did); a record from before
that counts as `unknown` rather than being left out. `repeated` counts a
search as a repeat when an earlier search within the last two minutes got back
the same top page — an agent re-searching with a paraphrase instead of
trusting the first answer, which is the pattern this number exists to
surface. Searches are grouped by session for this, except that every search
with no session at all shares one group instead of being left out: records
without a session — older logs, and clients that do not pass a session id, as
seen in a real log — are grouped as one stream, and that turned out to be
exactly where the real repeats were. Two searches in different, named
sessions never count against each other.

```
2026-08-17T18:31:03 … 2026-09-16T23:35:03

writes       24   (19 new, 5 merged, 0 unchanged, median 1536 chars)
refused       0   (0% of write attempts)
searches     41   (7% returned nothing)
            via: cli 38, mcp 3
            miss: terminal pane rendering Zenith Tauri
repeated      6   (15% of searches re-returned a top page seen within the previous 2 minutes)
touching      47   (3 measured, 1 found no page touching the path)
            miss: src/legacy/pty-pool.ts
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
[installation](installation.md#uninstalling) — in the global files and in every
project `lore init --scope project` connected, wherever you run it from: init
records each such project in `~/.pagelore/projects`. A recorded project that no
longer exists is reported and skipped. Projects connected by a version before
0.8.1 were not recorded; run `lore uninstall` inside each of them. `--yes` also
removes pagelore's own files in `~/.pagelore/` (the block, its version stamp and
the list of projects), and the directory once that leaves it empty; `--store home`
project stores in it are kept and listed.

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
typed. A search that passed `--touching` also logs `touched`: how many of the
returned hits were pages whose `sources` named one of those paths, so a search
that found nothing touching the path is distinguishable from one that never had
a touching page to find. Every search also logs `via`: `"cli"` when it ran
through the command, `"mcp"` through `lore mcp` — the two routes call the same
`search()`, so this is the only way to tell which one a line came from.
`lore stats` reads it: a refusal rate concentrated on one code usually means a
rule is wrong rather than the writer; searches that return nothing point at a
hole in the corpus or in ranking; a search re-returning, within two minutes, a
top page an earlier search already returned points at an agent re-asking
instead of trusting the first answer — records without a session (older logs,
and clients that do not pass a session id, as seen in a real log) are grouped
as one stream, since that is where the pattern actually turned up;
`--touching` searches that found no page point at a source no page cites yet;
sessions that searched and never wrote are the write side's "did it happen".

Set `PAGELORE_NO_LOG` (any non-empty value) to turn logging off entirely —
`log_event` then writes nothing. Meant for measurement runs (`evals/speed.py`
sets it on every process it spawns), not for normal use: a store you point a
benchmark at should not end up with benchmark queries in its log.
