---
slug: doctor-flags-a-shadowing-lore
title: "doctor names a shadowing lore on PATH"
kind: bug
created: 2026-09-20
updated: 2026-09-20
checked: 2026-11-04T15:25:57+00:00
sources:
  - src/pagelore/doctor.py
  - tests/test_init.py
---

## Cause

The smoke rehearsal exposed a trap no check named: an old `lore` (0.3.x) stays
first on PATH while the tree's own build is rehearsed, and `lore doctor` printed
both paths but marked the check ok. The bite is in the MCP handshake, which runs
`lore mcp` from PATH — the old server answers tools/list wrong or not at all, and
most harnesses report that quietly.

## Decision

`lore doctor` now probes the command its PATH resolves with `--version` and
compares the install directory that binary prints against this file's directory
(`_same_install`). The probe runs the binary because only it can say where it
lives; `which` cannot see through a pipx shim or an npm copy. A binary that will
not answer `--version` is reported as the old-build case of the same fault. Seen
from the other side, the same trap drove `tools/smoke.sh` to lead PATH with the
freshly installed command ([[local-release-rehearsal]]).
