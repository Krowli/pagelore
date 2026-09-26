# Project memory

This repository is the source of `pagelore`. The contract below is the same one
the installed command writes into an agent's instruction file — the difference is
that a clone has no installed `lore` yet, so run the module directly:

```bash
python3 -m pagelore search "your query"        # from the repo root, with src/ on sys.path
```

`pip install -e .` (or `pipx install -e .`) puts `lore` on PATH and the commands
below work verbatim. The canonical text lives in `src/pagelore/data/AGENT.md` and
is rendered into `AGENTS.md`; if the two ever disagree, that file wins and
`tests/test_instruction_block.py` fails.

Durable decisions, contracts and bug post-mortems live as markdown pages in
`.memory/`.

**Before stating anything about this project** — what it is, what it does, how a
part of it works, why it is that way, what was decided or rejected — and before
changing an unfamiliar subsystem, search first:

```bash
lore search "your query"
```

Query words are OR'd and ranked, so give several. Open a full page with
`lore show <slug>`. A hit marked `⚠ superseded by <slug>` was replaced — read the
replacement first. If nothing relevant comes back, say so rather than guessing.

The trigger is the kind of claim you are about to make, not the wording of the
question; "how does X work" and "what do you know about this project" are memory
questions too. This file is not a substitute for the search — it carries
instructions rather than reasons, and it goes stale while a page stays dated and
sourced. Skip the search only for mechanical work (a command, a typo, a rename)
and for general programming questions.

**After an architectural decision, a non-obvious bugfix, or a contract change**,
write the page:

```bash
lore write --slug short-kebab-slug --title "One line" --kind decision \
  --source path/to/file --body -   <<'PMEOF'
## Cause

What a future agent could not reconstruct from the code...
PMEOF
```

`--kind` is one of `decision`, `bug`, `concept`, `howto`. The terminator is
`PMEOF`, not `EOF`, so a page that documents heredocs cannot end its own body
early. When a decision reverses an earlier one, add `--supersedes <old-slug>`:
that stamps the old page and demotes it, instead of leaving two pages that both
read as current.

The command validates and rejects: no sources, a source path that does not exist,
a resulting page too short to be worth keeping. A rejection exits non-zero and
prints a `FIX:` line with the command to run instead — follow it. A page written
by hand is refused on the next read, because hand-edited frontmatter is the one
input the parser cannot round-trip.

Re-running the same slug replaces same-header sections in place and appends new
ones, so amendments are cheap and safe.

Skip this for typos, reverts, formatting and test-only edits. One topic per
page; cross-link with `[[other-slug]]`.

## Working on this repository

- `pytest` and `PAGELORE_NO_FTS5=1 pytest` both have to pass; the second
  covers the scan ranker that answers when SQLite has no FTS5.
- `ruff check .` — line length 100, target `py39`.
- The version is one literal in `src/pagelore/__init__.py`, plus the copy in
  `npm/package.json` that npm cannot derive. `tests/test_version_is_single_sourced.py`
  enforces that. After a bump, regenerate the pointer file, which carries a version
  stamp, and refresh the editable install so its metadata agrees:

  ```bash
  python3 -c "import sys; sys.path.insert(0,'src'); from pagelore import instructions; \
    open('AGENTS.md','w').write(instructions.render())"
  pip install -e .
  ```
- No proposal lands without a number from `evals/` or a failing test it fixes.
