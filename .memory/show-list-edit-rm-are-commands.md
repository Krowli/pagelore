---
slug: show-list-edit-rm-are-commands
title: "Opening, listing, editing and deleting pages are commands, not shell recipes"
kind: decision
created: 2026-09-20
updated: 2026-11-04
checked: 2026-11-04T15:26:26+00:00
sources:
  - src/pagelore/cli.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/edit.py
  - src/pagelore/listing.py
  - src/pagelore/remove.py
  - src/pagelore/show.py
---

## Context

The store had one command for reading it, `search`, and the contract finished the
job with `cat <store path>/<slug>.md`. That was correct and it was not typed: the
store path is absolute and appears once, on the first line of a search result, so
opening a page meant copying it out. Listing meant `ls .memory`, which shows
filenames and not which pages were superseded. Editing meant opening the file and
hoping the frontmatter survived. Deleting meant the shell's `rm`, which the store's
log never saw, so `stats` counted a write that led nowhere. And `--version` existed
and worked while the one screen a person reads never mentioned it, so the first
person to look for the version concluded there was none.

## Decision

`lore show <slug>` prints the page verbatim, frontmatter included, and says on
stderr when the page was superseded and what to read instead. The contract in
`data/AGENT.md` now says `lore show <slug>` where it said `cat`; the repo's
`CLAUDE.md` says the same. `lore list` prints every page newest first with kind,
date, title and a `⚠ superseded by` marker. `lore edit <slug>` opens the page in
`$VISUAL`, else `$EDITOR`, else `vi` (`notepad` on Windows), and when the editor
closes it re-parses the page and warns if the body fell under `MIN_BODY` — the one
way a hand edit goes wrong silently, because search does not refuse a thin page, it
skips it. `lore rm <slug>` deletes and logs a `remove` event. `lore version` is a
word as well as a flag, and the bare command lists it.

All four take the slug a search printed, look it up by frontmatter slug (`edit` and
`rm` through `lib.find_page`; `show` matches the same slug in its own
`load_pages` list, which it reuses for backlinks) — so the symlink and non-file
filters apply — and refuse a missing one through `lib.refuse_missing`: exit 2,
`no page 'x'`, and a `FIX: lore search 'x'` line, because an agent that typed a
slug from memory is one search away from the right one and its loop already
follows `FIX:`.

## Why the module names differ from the command words

`list` is a builtin and `rm` reads as the shell's, so the modules are `listing.py`
and `remove.py` and `cli.MODULES` maps the word to the module. Everything else keeps
the rule that the command word is the module name.

## What was not done

No confirmation on `rm`: git, npm and pipx do not ask either, and the log records
what happened. No `--json` on `list` until someone needs it; `search --json` exists
for the agent path. `show` does not log a read event, because the log exists to
count refusals and queries, and a read is neither.
