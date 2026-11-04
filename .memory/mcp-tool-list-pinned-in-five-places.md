---
slug: mcp-tool-list-pinned-in-five-places
title: "The MCP tool list is pinned in five places, two of them outside pytest"
kind: bug
created: 2026-11-04
updated: 2026-11-04
sources:
  - tools/smoke.sh
  - .github/workflows/test.yml
  - src/pagelore/doctor.py
  - src/pagelore/mcp.py
  - evals/agent_eval.py
---

## Cause

Adding `memory_confirm` to `lore mcp` passed the whole pytest suite. Then the local
release rehearsal (`make smoke`) failed, because `tools/smoke.sh` asserted the exact
set `{memory_search, memory_write}`. The CI install-smoke job in
`.github/workflows/test.yml` carried the same assertion, so the first push to main
would have gone red.

## Where the tool list is pinned

The set of tool names is a contract checked in five places, and a new tool has to
reach all of them:

- `src/pagelore/mcp.py` — `TOOLS` and the dispatch table in `handle`
- `src/pagelore/doctor.py` — `_handshake` expects the exact set; an old install
  earlier on PATH fails here on purpose
- `tests/test_mcp.py` — the `tools/list` order and the stdout transport test
- `tools/smoke.sh` and `.github/workflows/test.yml` — the installed wheel's
  `tools/list`
- `evals/agent_eval.py` — `MCP_TOOLS`, the `--allowedTools` an MCP session gets

Tool names and descriptions are measured text ([[mcp-offered-as-a-choice]]), so a
change also needs an agent_eval run on the mcp arm
([[pages-confirmed-against-code]] is the run for `memory_confirm`).
