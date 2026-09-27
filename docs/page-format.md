# Page format

One file per topic at `.memory/<slug>.md`, written by `lore write`. Write
them through the script: it validates them, and hand-edited frontmatter is the
one input the parser cannot round-trip. A page written by hand is still read,
but search skips it while it is under 200 characters and marks it while it has
no sources, and names it so it can be rewritten through the script.

Frontmatter is YAML-ish and parsed leniently. This is the contract:

| Field | Required | Notes |
|---|---|---|
| `slug` | yes | lowercase, digits, single hyphens; matches the filename |
| `title` | yes | one line, quoted |
| `kind` | yes | exactly one of `decision`, `bug`, `concept`, `howto` |
| `created` / `updated` | auto | ISO dates, managed by `lore write` |
| `sources` | yes | file paths this page explains; each must exist at write time |
| `supersedes` | no | slugs this page replaces (`--supersedes`) |
| `status` / `superseded_by` | auto | stamped on the page that was replaced |

`kind` is a hint rather than a taxonomy, but it is a closed set: the corpus this
was designed against grew a machine-generated fifth kind to 23% of all pages and
none of it was worth reading.

`sources` is accepted both inline (`sources: [a.ts, b.ts]`, written by older
pages) and as a block list. The parser handles both; the writer always emits the
block form. A single unquoted value is read as a one-item list.

Any field the tooling does not own is **preserved verbatim** across writes, so
the format can be extended without a migration.

```markdown
---
slug: webgl-context-loss
title: "xterm WebGL context loss on display sleep"
kind: bug
created: 2026-08-08
updated: 2026-08-17
sources:
  - src/terminal/renderer.ts
---

## Cause

The WebGL renderer loses its context when the display sleeps; xterm never
repaints because the addon does not observe `webglcontextlost`.

## Fix

Listen for the event and re-attach the addon. See [[terminal-renderer-choice]].
```

## Conventions

Write the body for someone who has forgotten the incident: what was observed,
why it happened, what was decided, and what would make you revisit it. One topic
per page — if a page needs "and also", split it. Cross-reference with
`[[slug]]`, which is the page's filename without the extension, so following one
is a single read. `[[slug|anchor text]]` names the target the same way and lets
the link read naturally in a sentence. A link inside a fenced code block or an
inline code span is read as literal text, not a cross-reference, so quoting
`[[slug]]` in an example does not count as one.

`lore write` warns, on stderr, when `[[slug]]` names no page in the store — it
does not refuse the write, because an agent often writes the page that explains
something before the page it points at exists yet. `lore show <slug>` prints, also
on stderr, which other pages link to the one being shown, so the reverse
direction does not require reading every page by hand.

Re-running the same slug replaces same-header sections in place and appends new
ones; the command prints what it replaced. Sections are matched on `## ` lines
outside code fences, so a page may quote markdown safely.

When a decision reverses an earlier one, record the new page with
`--supersedes <old-slug>`. That stamps the old page as superseded, demotes it in
ranking, and marks it in every result line — the alternative is two pages that
both read as current.
