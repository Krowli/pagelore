---
slug: import-hop-measured
title: "Import-graph neighbours for --touching: measured, not built yet"
kind: decision
created: 2026-09-27
updated: 2026-09-27
sources:
  - evals/import_probe.py
  - src/pagelore/search.py
---

## Question

`lore search --touching FILE` finds only pages whose `sources` cite FILE or a
directory above it. The legacy wiki-core scanned every code file and linked them
by imports. Would one hop over imports (FILE imports X, or X imports FILE, and a
page cites X) surface useful pages for a file no page cites, or just noise?

## Measurement

`evals/import_probe.py --repo PATH` parses imports with the stdlib only: Python
via `ast`, TS/JS and Rust via regex, relative specifiers only. The thresholds
were fixed before the run: reach >= 20% of uncited files, leave-one-out recall
>= 0.5, and a median non-empty neighbour group <= 3 pages, evaluated per hub cap
N in {inf, 10, 5}. On this repository (60 code files, 34 current pages):

    cap   reach  LOO recall  LOO med.grp  med.nonempty  p90 nonempty
    inf   96.4%       71.2%         14.5           9.0          13.0  fail
     10   32.1%       54.5%          5.0           1.0          11.0  pass
      5   32.1%       54.5%          5.0           1.0          11.0  pass

The probe prints `VERDICT: build (hub cap 10)`.

## Decision

Not built for now. The pass is narrow, and it rests on two things that do not
generalise:

- it comes from one repository, and one whose pages already cite 18 of 20 files
  in `src/`;
- it depends on which noise metric gates. The leave-one-out group, which is the
  group an agent actually sees when the right page is found, has a median of 5
  pages, above the threshold of 3.

Two earlier runs of the probe gave the opposite verdict. The first came before a
resolver bug was fixed: `from pagelore import search` was resolved to
`__init__.py` instead of `search.py`. The second gated at hub cap inf only. Both
are superseded by the table above.

## What would change it

- `lore stats` now reports how many measured `--touching` searches returned no
  touching page (the `touched` log field). A high miss rate on real use is the
  demand signal.
- A second repository with a live store that clears the same thresholds.

If both appear, build it as a separate group below exact matches, with the hub
cap chosen by the probe and a hard sort key rather than a score bonus, as
[[search-by-touched-file]] requires.
