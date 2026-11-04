---
slug: mcp-sends-instructions-on-connect
title: "lore mcp sends the block's own paragraphs as its initialize instructions"
kind: decision
created: 2026-09-26
updated: 2026-11-04
checked: 2026-11-04T15:26:58+00:00
sources:
  - evals/mcp_probe.py
  - src/pagelore/data/AGENT.md
  - src/pagelore/instructions.py
  - src/pagelore/mcp.py
---

## Decision

The `initialize` reply of `lore mcp` now carries `instructions`. An agent with only
the server connected had nothing but two tool descriptions to learn from; the
instruction-file route hands it the whole contract every turn.

The field is in the 2025-06-18 schema the server speaks (`InitializeResult`, in
`schema/2025-06-18/schema.ts` of modelcontextprotocol/modelcontextprotocol, and the
lifecycle page https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
shows it in the example reply): optional, "Instructions describing how to use the
server and its features ... It can be thought of like a 'hint' to the model. For
example, this information MAY be added to the system prompt."

## One source, not a second copy

The text is derived from `src/pagelore/data/AGENT.md`, not written beside it. A
paragraph there preceded by `<!-- mcp -->` goes into the instructions; one preceded by
`<!-- mcp <tool> -->` ends in the colon that introduced a shell command, and in the
instructions that colon becomes "with `<tool>`". `render()` strips the markers, so
the file an agent reads is unchanged except that one paragraph was split into three
(same words, same order) so the part that says "this file is not a substitute"
could be left out of a text that is not a file.

Not the whole block: it is 3.6k characters, most of it shell commands a tool user
cannot run, and a client puts this text next to every other server's. The derived
form is 1463 characters (1184 when the measurement below was taken). Tests pin both tool names, the bound (≤ 2500), no shell
command leaking in, and that editing a marked paragraph changes the output.

## Measured

`evals/acceptance.py --pointer mcp`, MCP alone on Claude Code's default settings
(tool search on), Claude Code 2.1.281, 2026-09-26, the command recorded in
[[mcp-offered-as-a-choice]]:

| | searched before answering |
|---|---|
| before, no `instructions` | 4/10 |
| after, with `instructions` | 10/10 (9 of 10 answers named the canvas decision) |

`python3 evals/mcp_probe.py --handshake` shows what arrives without a model: protocol
2025-06-18, instructions 1184 characters at the time (1463 now), both tool names present.

The default `lore init` recommends stays the file for now: this is one harness
version, ten runs per arm, and the file arm has never missed. What would move it is
the same 10/10 on a second harness or a re-run of the full three arms.
