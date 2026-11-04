---
slug: python-and-the-floor-that-was-not-earned
title: "Why Python, and why the floor is 3.9 rather than 3.11"
kind: decision
created: 2026-09-18
updated: 2026-09-18
checked: 2026-11-04T15:27:37+00:00
sources:
  - pyproject.toml
  - install.sh
  - docs/research/runtime-portability.md
---

## Why Python at all

Asked late, never recorded, so the answer was reconstructed and then checked
against what everyone else does (`docs/research/runtime-portability.md`).

The standard library covers the whole product: `sqlite3` with FTS5 for the index
cache, `unicodedata` for the NFC normalisation without which macOS filenames and
Cyrillic bodies are unfindable, `re`, `json`, file locking. Zero dependencies,
and no build step — the skill is a directory of text files, which is all five
plugin systems can install, because none of them runs a build or puts anything
on PATH.

The surveyed field agrees by a wide margin. Anthropic's own skills repository is
70 `.py` against 2 `.sh`. Every memory competitor demands *more* than this one:
Basic Memory wants Python 3.12 through `uv`, the closest architectural twin
wants Python 3.12 plus `uv` plus a clone plus a manual PATH edit, mem0 wants Node
or Python **and an API key**.

## Why not shell, and why not a binary

There is no runtime present by default on macOS, Linux and Windows at once —
none. POSIX shell, `sqlite3` and `perl` are absent on Windows; PowerShell is
Windows-only; Windows ships a `python.exe` stub that exists only to return an
error. So no language choice makes the dependency disappear; it only moves.

Ranked search in shell has a measured price: `session-cartographer` implements
it in awk and needs 12 KB of awk plus 83 KB of bash, and its own README reports
**~11 seconds** per query on a 122 000-record corpus against tens of
milliseconds for the non-portable path. The whole shipped search here is 72 ms.

The one project that genuinely covers Windows keeps twins — 206 `.sh` beside 123
`.ps1` — and what it twins is file shuffling, not a ranker. A second
implementation of BM25F, NFC folding and the FTS5 schema, kept in sync by hand,
is not worth a platform where the developer has already installed something.

No plugin surveyed ships a compiled binary through the plugin copy. Zero. The
ones that use binaries install them out of band, which is a second install step
the user performs.

## The floor was not earned

`pyproject.toml` said 3.11 and `install.sh` refused anything below it. A stock
macOS ships **3.9.6**, so on a clean Mac the installer hard-failed and the
skill would not run until the user installed a Python — the exact barrier that
prompted this question.

Nothing required 3.11. No `match`, no `tomllib`, no `ExceptionGroup`, no
`StrEnum`, no `datetime.UTC`; all five scripts already carry
`from __future__ import annotations`, which is what makes the `X | None`
annotations legal on 3.9. Measured before changing anything: `py_compile` clean
under 3.9.6, and the full suite **214 of 214 passing** on the system
interpreter. The floor is now 3.9 and CI runs it, because a floor that is
declared rather than tested is how this one drifted.

What this does not fix is Windows, where there is no Python at all. That stays a
documented prerequisite rather than a solved problem.
