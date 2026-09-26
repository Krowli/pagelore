---
slug: one-name-pagelore
title: "Everything project-memory became pagelore, with a migration instead of a shim"
kind: decision
created: 2026-09-26
updated: 2026-09-26
sources:
  - src/pagelore/instructions.py
  - src/pagelore/init.py
  - src/pagelore/lib.py
  - src/pagelore/doctor.py
  - tests/test_rename_migration.py
---

## Decision

0.6.0 renames the last `project-memory` surfaces to `pagelore`: the home directory
(`~/.pagelore`), the environment variables (`PAGELORE_*`), the MCP server name, the
cache directory and the GitHub repository. The package and command names were
already `pagelore`/`lore` because `project-memory` and `lore` are taken on PyPI and
npm ([[installed-command-not-copied-directory]]). The per-project store stays
`.memory/`: it is generic, and it is user data.

## How an upgrade arrives without hand edits

- **Home directory.** `init.migrate_legacy_home` runs before every command (unless
  `PAGELORE_NO_REFRESH`) and at the start of `lore init`. One `os.rename`, then a
  symlink at the old path. The link is not a shim for its own sake: `--store home`
  projects have a `.memory` symlink into `~/.project-memory/<project>` in repositories
  no program can enumerate, and without the link every one of those stores would go
  dark with no error. Includes in the managed block of the global Claude/Gemini files
  and the current project's files are repointed; a line outside the fence is not.
  If both directories exist, nothing is merged — `doctor` reports it. An explicit
  `PAGELORE_HOME` disables the move.
- **Environment.** `lib.env(NEW)` reads `PAGELORE_X`, else `PROJECT_MEMORY_X` with
  one stderr warning per process. Stderr because stdout is `--json` or the MCP
  stream. The fallback is removed in 0.7.0.
- **MCP.** `init` replaces an old `project-memory` entry only if it equals a shape
  `mcp_entry` produces (an empty `env` tolerated, because `claude mcp add` stores
  one). An edited entry is the person's and is left; `doctor` flags it as
  `mcp-legacy:<agent>`. `uninstall` removes both names.

## Rejected

- Merging two home directories: one of them is someone's, and a merge has no
  correct answer for a conflicting `AGENT.md` or a same-named project store.
- Repointing every `.memory` symlink: their locations are unknown.
