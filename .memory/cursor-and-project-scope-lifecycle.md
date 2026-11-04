---
slug: cursor-and-project-scope-lifecycle
title: "Cursor joins init; uninstall and doctor cover project scope and CODEX_HOME"
kind: decision
created: 2026-09-26
updated: 2026-09-26
checked: 2026-11-04T15:25:56+00:00
sources:
  - src/pagelore/init.py
  - src/pagelore/uninstall.py
  - src/pagelore/doctor.py
---

## Decision

`lore init` gains a fourth agent, Cursor. Its MCP entry goes to `.cursor/mcp.json`
(project) or `~/.cursor/mcp.json` (global) with `type: "stdio"` — Cursor's docs mark
`type` required in the field table even though their examples omit it, so the
field is sent. Its file route is the project's `AGENTS.md`, the same file Codex
reads; at global scope Cursor has no file (user rules live in Customize → Rules),
so `agent_files()` returns None for it and init says what to paste.
`uninstall` never deletes a `.cursor/mcp.json` it emptied, because Cursor itself
writes that file too — unlike `.mcp.json`, which only we write here.

## Why the agent table became a function

`AGENTS` was a module constant resolved at import, so `HOME` and `CODEX_HOME`
were frozen at import time and tests had to monkeypatch the dict. Codex reads its
global `AGENTS.md` from `$CODEX_HOME` (default `~/.codex`), the same directory as
`config.toml`; the MCP code already honoured it and the file route did not.
`agent_files()` and `codex_home()` resolve per call, and both routes share them.

## Project scope in uninstall and doctor

Blocks written with `--scope project` sit in the repo's `CLAUDE.md`, `GEMINI.md`,
`AGENTS.md`. Uninstall only walked the global files, so those blocks survived and
dangled once `~/.project-memory` was removed; doctor reported "nothing connected"
for a project that was connected. Both now include the project files when a git
root is found; doctor emits `project:<file>` rows only for files that carry the
fence, so an unrelated repo produces no noise.

## unchanged and --json

`replace_block` and `merge_json_server` return `unchanged` and the caller skips the
write, so a re-run does not touch mtimes. `--json` wraps the human stream in a
`Recorder` on stderr; the JSON's `changes` are the same `report()` lines, so the
two outputs cannot disagree.
