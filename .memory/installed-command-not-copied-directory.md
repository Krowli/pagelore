---
slug: installed-command-not-copied-directory
title: "The program is an installed command, and what that cost"
kind: decision
created: 2026-09-19
updated: 2026-11-04
checked: 2026-11-04T15:25:56+00:00
supersedes:
  - pointer-files-per-install-mode
sources:
  - evals/acceptance.py
  - npm/bin/lore.js
  - pyproject.toml
  - src/pagelore/cli.py
  - tools/retarget_sources.py
---

## Context

Up to 0.3.5 this shipped as a directory that five plugin systems copied. The
command an agent had to run was an absolute path that differed per install mode,
and [[pointer-files-per-install-mode]] records the bug that follows: a user with a
project-scoped install ran the documented verification command and got
`No such file or directory`. Three other costs came from the same shape — the
version lived in ten hand-edited places guarded by five drift tests, an update
reached nobody unless a manifest was bumped (it happened twice in one month), and
`pyproject.toml` declared `py-modules = []` so the built distribution had never
once contained the program.

## Decision

One installed command. `pipx install pagelore` or `npm install -g pagelore`, then
`lore init`. `lore search "…"` has no path in it, so it is correct in every layout
instead of in one of three, and that whole class of bug is structurally deleted
rather than fixed — which is why this page supersedes the one describing it.

## Why the name is pagelore and the command is lore

Not a preference. `project-memory` was already taken on **both** PyPI and npm, by
near-identical competitors describing themselves as a repo-scoped memory engine for
AI agents, and `pm` was taken on both as well. `project-memory-cli` on npm was
claimed after this repository already existed. There was no free name to keep, so
the rename is forced, and anyone reading the release notes should be told that
rather than left to read it as churn.

## What dropping the Agent Skills packaging cost, measured

The hope was that it cost nothing. It did not.

`evals/acceptance.py --pointer none`, fifteen real Claude Code sessions per arm,
one question only the store can answer, a pass requiring a search *before* the
answer:

- Before, on the v0.3.5 tree — a registered skill directory, no instruction line
  anywhere: **15/15 searched**. The harness's own skill index was enough on its
  own.
- After — nothing registered, no line, no tools: **0/15**.

So the manifest was a working discovery fallback, not dead weight. The trade was
taken because the recommended setup is 15/15 either way and the maintenance cost of
six manifests was real, but the honest statement is that a user who installs and
then connects nothing is worse off than before. Three things now cover that gap and
none of them existed while the skill directory was doing the work: `lore init` runs
at install time and offers the line, `lore doctor` reports an unconnected install
as a fault rather than a neutral state, and a bare `lore` ends with one line saying
so. If a future measurement shows those are not enough, the answer is to make them
louder, not to bring the manifests back — they were not free, and they only ever
helped Claude Code and Codex.

## Why sources were repointed by hand rather than through the command

Fifteen pages in this store cited paths that moved. Amending them through
`lore write --source <new path>` looks right and is wrong: `write_page` unions the
sources it is given with the ones already on the page and never removes one. Every
page would have ended up citing both the live path and the dead one, exit 0,
silently, and `--touching` would over-match on the dead path forever.

So `tools/retarget_sources.py` edits the `sources:` lists and nothing else. It
does not bump `updated:` — the content did not change that day, and that date feeds
ranking as well as a reader's judgement of how current a page is. Pages already
superseded keep their dead sources, because their value is the record of what was
tried and pointing them at files that never held that decision would falsify it.

One live page is also left with a dead source on purpose:
`python3-is-not-a-windows-command` cites `hooks/hooks.json`, and the lesson it
carries has no home in the tree until the npm shim's interpreter list is the thing
that depends on it.

## Rejected

**Keeping a skill manifest alongside the CLI**, to get the 15/15 discovery back.
It reintroduces exactly the maintenance the repackage exists to remove — a version
in another file, a manifest to validate in CI, a second install route to document
— and it is Claude-Code-and-Codex-only, so it does not help the harnesses this
project claims to support. Measured discovery is worth less than the invariant that
there is one way to install this.

**A `postinstall` script on the npm side that pip-installs the Python.** It is what
a corporate registry mirror and `--ignore-scripts` both break, and it fails at
install time in a way the user cannot act on. The Python is vendored into the
tarball at pack time instead, and CI hash-compares it against `src/` so the copy
cannot drift.

**Pointing the agent's instruction line into the pipx virtualenv.** The path
contains `python3.13`, so it dangles silently after a Python upgrade — no error,
the agent simply stops searching months later. A symlink has the same failure
behind a stable-looking path. The block lives at `~/.pagelore/AGENT.md` and
every `lore` invocation refreshes it, which costs 80 µs against a 52 ms search and
never creates the directory: its existence is the opt-in signal.
