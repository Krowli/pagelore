---
slug: links-checked-not-refused
title: "Dangling [[slug]] links warn; lore show reports backlinks"
kind: decision
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/lib.py
  - src/pagelore/show.py
  - src/pagelore/write.py
---

## Why a dangling link warns instead of refusing

`lore write` parses every `[[slug]]` in the resulting (merged) page body and
checks each distinct target against the store. A target with no `<slug>.md`
prints `⚠ [[x]] names no page in this store — write it, or fix the slug` on
stderr and logs `dangling_link` in the write event's `warnings` field — but the
write still succeeds, exit code 0.

This has to be a warning, not a refusal through `reject()`, because the write
order two related pages come out in is not under the tool's control. An agent
investigating an incident often writes the explanation (page A, "the bug was
X, see `[[the-decision-that-caused-it]]`") before it writes the decision page
itself (page B) — sometimes in the same session, sometimes days apart if B
needs more digging. Refusing A's write until B exists would force an artificial
order or an empty stub for B just to satisfy the gate, which is exactly the
kind of stub-generation this store's write-time checks exist to prevent
elsewhere. A wrong slug (typo, renamed page) is the same signal either way —
worth surfacing, not worth blocking on — so both cases get the same warning
rather than trying to distinguish "not yet written" from "never going to
exist."

Self-links are explicitly excluded from the dangling check (`target ==
args.slug` short-circuits before the filesystem check): a page linking to its
own slug while it is being created for the first time cannot pass a
"does `<slug>.md` exist" test, since the file does not exist until the write
completes, but it is not a broken reference.

## Why backlinks live on stderr in `lore show`

`show`'s stdout contract is "byte-identical to the file on disk"
(`tests/test_show.py`), the same contract that already put the superseded
notice on stderr rather than stdout. Backlinks are computed information, not
page content — `load_pages(store)` plus `links(p.body)` over every other page,
filtered to those naming the shown page's slug — so they follow the same rule
as the superseded line: printed on stderr, after it, only when the set is
non-empty. This keeps `lore show <slug> > file.md` a safe way to extract a
page verbatim while an interactive caller still sees who else points here,
which was previously only discoverable by grepping the whole store by hand.

## Implementation note

`lib.links(body)` returns targets in appearance order, duplicates included,
because its two callers want different things from the same scan: `write.main`
wants first-appearance order over distinct targets for the warning list, while
`show.main` only checks set membership per candidate page. Fence-skipping
reuses `_FENCE`, moved from `write.py` into `lib.py` so there is exactly one
copy of the fence-open/close regex that `split_sections` and `links` both rely
on to agree about what counts as "inside a code block."
