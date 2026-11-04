---
slug: local-release-rehearsal
title: "The release path rehearses locally, without publishing"
kind: decision
created: 2026-09-20
updated: 2026-09-20
checked: 2026-11-04T15:26:12+00:00
sources:
  - tools/smoke.sh
  - Makefile
  - evals/acceptance.py
  - .github/workflows/test.yml
---

## Cause

Testing a change meant publishing it: the only way to run a new build as a user
was to release and reinstall, so a small edit cost until the release pipelines
finished. CI already encoded what a user does — its install-smoke builds the
wheel, pipx-installs it, and runs write/search/--touching/stats/doctor plus the
whole MCP route — but nothing could run those same steps locally.

The rehearsal immediately exposed the two-lores trap, which was the real reason
local testing lied. `lore doctor` proves the MCP handshake by running `lore mcp`
from PATH, and the `lore` on this machine's PATH was a 0.3.x build with no `mcp`
command: the handshake failed (exit 2, `unknown command 'mcp'`) even though the
freshly installed wheel was fine. A user with a released build on PATH and a dev
build in another venv sees exactly the same failure. CI never sees it only
because it leads PATH with the directory it just installed into.

## Decision

`tools/smoke.sh` — one command, about a minute: `pip wheel` (no extra build
dependency), install the wheel into an isolated environment (pipx into a scoped
PIPX_HOME when present, else a throwaway venv), lead PATH with that bin dir the
way pipx's ensurepath does, and run under a throwaway HOME the same end-to-end
steps CI runs — including the MCP route through init, doctor and uninstall.
`Makefile` (`make dev` / `make test` / `make smoke`) spells the loop, and
`evals/acceptance.py` gains `PAGELORE_BIN` so an acceptance measurement runs the
tree's own build rather than the first `lore` on PATH.

The rule it encodes: the stale `lore` on PATH is not an obstacle to testing, it
is exactly the failure mode the local rehearsal must be immune to. PATH leading
with the thing just installed is part of the rehearsal, not an implementation
detail.

## Rejected

Pointing the rehearsal at the machine's real pipx install. A rehearsal that
clobbers the release it stands in for is not a rehearsal.
