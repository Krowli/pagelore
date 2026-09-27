---
slug: sources-drift-marked-from-git
title: "Sources drift is marked from git commit time, not mtime or updated"
kind: decision
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/freshness.py
  - src/pagelore/search.py
---

## Cause

`lore search` and `lore show` needed to tell an agent that a page's `sources`
moved on after the page was written, without touching ranking. Three clocks
were available and two were rejected.

`updated` in the page's own frontmatter was rejected: it is day-granular (one
value per calendar day, however many writes land that day) and it is written
*before* the commit that carries the page exists — so it cannot honestly answer
"which came first, this page or that source's last change" against a source's
own commit history, which is timestamped at commit, not at edit.

File mtime was rejected: a fresh clone or a CI checkout stamps every file with
the checkout time, so every page in the store would read as freshly stale on
the very first run after cloning — the false-positive rate would be total.

Git commit time was chosen because it is the one clock both the page file and
every source file are already stamped with, on the same scale, and it survives
a clone untouched. A source is `changed` when its last commit is strictly newer
than the *page file's* own last commit. A page and its source landing in the
same commit read as fresh, not stale — same clock reading, not two — which also
means the very first commit that adds a page together with the sources it
describes is never marked, only a source edited after the fact is.

## No git, no markers

`gone` needs to resolve a source against the project root, and sources are
cited root-relative — the one thing this project does not otherwise need to
know reliably regardless of where a command is invoked from. Git is the only
thing here that names that root authoritatively (`-C <store.parent>` succeeding
at all *is* the check). So if git cannot answer — not a repository, the `git`
binary is missing, the call times out — both markers are withheld entirely,
including `gone`, rather than guessed from a weaker signal. An uncommitted page
file gets the same partial treatment for the same reason: with no commit for
the page there is nothing to compare the source's commit time against, so
`changed` is skipped for that page specifically, while `gone` (a filesystem
check, not a git-history one) still fires normally.

`--relative` on the `git log` call matters for the same reason: a store living
in a subdirectory of a larger repository has a git top-level above its project
root, and without `--relative` the `--name-only` listing comes back relative to
that top-level while the pathspecs after `--` were resolved relative to
`-C <root>` — two different bases for the same paths, silently never matching.
`--relative` makes the listing relative to `-C`'s directory too.

## Why annotate() sits outside search()

`search()` is called on the order of hundreds of times by `evals/run.py` in one
run; putting a `git log` subprocess inside it would tax every evaluation query
for a feature evals never look at. `search.annotate(hits, store)` runs once,
after ranking has already produced the final hit list, and only `search.main`
and `mcp.do_search` call it — never `search()` itself. Its result lives in the
module global `last_drift`, the same idiom as `last_touching`/`last_path`, and
it is unconditionally reassigned on every call (even for zero hits) so a
previous query's markers can never survive into the next one — `lore mcp` is a
single long-lived process serving many searches in a row.

## Where it does not reach

Ranking is untouched: a stale or gone-sourced page is not demoted, only marked.
`evals/run.py --by-type` produces byte-identical output before and after,
because it never calls `annotate()`. The check is a pure add-on to the two places
that print a finished hit list: `format_hit` and `lore show`.

A page that was never committed — the default gitignored store
(`lib.ensure_store` adds `.memory/` to `.gitignore`), a `home` store outside the
repository, or a page not committed yet — is compared by its file's mtime
instead of a commit time. A clone never creates such a file, so its mtime is the
time it was last written, not a checkout time; a tracked page keeps using its
commit time for exactly that reason. Until 0.8.2 such pages were skipped and
only `gone` could appear for them, which left `changed` dead in the default
mode. The first fix only documented the limit; it was then fixed.

Two more spellings `_matchable` does not paper over:

- A source cited as a directory (e.g. `--source src/widgets`) never gets
  `changed`. `git log --name-only` prints the individual file paths a commit
  touched, never the directory argument itself, so the directory string cited
  on the page never appears in git's output to match against.
- A source cited with Windows-style backslashes (`src\a.py`) never matches
  either. Git always prints paths with forward slashes regardless of platform,
  and `_matchable` uses `posixpath.normpath`, which does not treat `\` as a
  separator at all, so the two spellings are never brought together.
