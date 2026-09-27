---
slug: legacy-copies-removed-by-uninstall
title: "uninstall, doctor and init find the pre-0.4.0 copied project-memory install"
kind: decision
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/init.py
  - src/pagelore/uninstall.py
  - src/pagelore/doctor.py
---

## Cause

Releases up to 0.3.x were not an installed program. `install.sh` copied a
`project-memory` skill into `~/.agents/skills/`, or into a project's
`.agents/skills/` with `--project`, and linked it from `.claude/skills/`. It then
wrote up to three hooks into `.claude/settings.json`, tagged
`_managed_id: project-memory-session-start|write-guard|session-stop`. The copied
scripts need only Python, so they kept working after the move to an installed
command ([[installed-command-not-copied-directory]]), and after `lore uninstall`
and `npm uninstall -g pagelore`.

On 2026-09-27 a repository (aioomi-modular-project/modular) still had such a
copy, 0.1.0. Its session-start hook announced the memory to every agent, and
agents kept calling `memory_search.py` after the user had removed pagelore.
Nothing in the current program knew the old layout existed; `doctor` checked
only `~/.agents/skills/project-memory`.

## Decision

`init.legacy_installs(roots)` looks under the home directory and each project
root (the one underfoot plus every remembered project, see
[[uninstall-walks-every-project]]) for:

- a `project-memory` directory under `.agents/skills/` or `.claude/skills/` that
  carries `scripts/memory_search.py`, or a dangling link of that name;
- `.claude/settings.json` holding a hook whose `_managed_id` starts with
  `project-memory`.

What each command does with them:

- `uninstall` removes them: links first, then the copy, then only the tagged
  hooks, keeping every other hook and setting.
- `doctor` reports each one as a FAIL row naming `lore uninstall`.
- `init` prints a warning with the same FIX.

## Rejected

- Deleting any `project-memory` directory by name. Someone else's skill can
  share the name, so a directory counts only if it carries the old scripts.
- Removing the hand-written "Project memory" sections some repositories put in
  AGENTS.md. They are prose a person wrote, with no fence to find them by.
