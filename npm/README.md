# pagelore

Durable project memory as markdown pages on disk, searchable without a server.

```bash
npm install -g pagelore
lore init
```

`lore init` writes the instruction block and offers to add the one line that
points your agent at it. It shows the exact change and asks before writing
anything; its default connects nothing.

Then, in any project:

```bash
lore search "terminal freeze webgl context lost"
lore write --slug webgl-context-loss --title "Why the canvas renderer is the default" \
  --kind decision --source src/terminal/renderer.ts --body - <<'PMEOF'
## Cause

What a future agent could not reconstruct from the code.
PMEOF
```

Pages live in `.memory/` in the project, as plain markdown you can read and diff.
Ranking is BM25F over title and body, with a SQLite FTS5 index used as a
disposable cache. No server, no embeddings, no network.

## This package needs Python

The program is Python; this package is a shim that finds an interpreter and hands
it the vendored source. Nothing is installed at install time — no `pip`, no
`postinstall` — so `--ignore-scripts` and a corporate registry mirror both work.

Python 3.9 or newer, which is what a stock macOS ships. If `lore` cannot find one
it says so and names every interpreter it tried. To pin one:

```bash
export PAGELORE_PYTHON=/usr/local/bin/python3.12
```

That variable is exclusive: if it names an interpreter that does not work, `lore`
fails and says so rather than quietly using a different one.

If you already have `pipx`, `pipx install pagelore` needs no Node at all and is
the same program.

## Everything else

Documentation, the evaluation numbers behind the ranking, and the reasons for each
design decision: <https://github.com/Krowli/pagelore>

PolyForm Noncommercial 1.0.0 — free for noncommercial use; commercial use needs a
separate license (lionmause999@gmail.com). Versions up to and including 0.7.0 stay under MIT.
<https://polyformproject.org/licenses/noncommercial/1.0.0>
