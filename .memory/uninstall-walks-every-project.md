---
slug: uninstall-walks-every-project
title: "uninstall cleans every project init connected, recorded in ~/.pagelore/projects"
kind: bug
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/uninstall.py
  - src/pagelore/init.py
---

## Cause

`lore uninstall` stripped the fenced block from the global files and from the
project under the current working directory only. `lore init --scope project`
can connect any number of repositories, and nothing remembered which. On
2026-09-27 a second repository (atlasian) still carried
`@/Users/krowli/.project-memory/AGENT.md` after an uninstall had reported
success: `--yes` had deleted the block file, so the include silently loaded
nothing — exactly the dangling-include failure uninstall exists to prevent.

## Fix

`lore init` appends the resolved project root to `~/.pagelore/projects` (one
absolute path per line, deduplicated) whenever it writes at project scope. It
does this before writing, so a partly written project is still found.
`uninstall` builds its list of project roots from the git root underfoot plus
every remembered project. It strips the block from each root's `CLAUDE.md`,
`GEMINI.md` and `AGENTS.md`, and removes the MCP entry from each root's
`.mcp.json`, `.gemini/settings.json` and `.cursor/mcp.json`. A remembered
project that no longer exists is reported and skipped. `projects` is one of
the program's own files, so `--yes` deletes it with the block and the stamp.

## Limits

Projects connected by a version before this change were never recorded, so
running `lore uninstall` inside each of them is still the only way to clean
them. The list is not pruned when a project is cleaned without `--yes`; a
second uninstall simply finds nothing to remove there.
