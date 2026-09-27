---
slug: secrets-refused-at-write
title: "lore write refuses committed credentials, warns on high-entropy strings"
kind: decision
created: 2026-09-27
updated: 2026-09-27
sources:
  - src/pagelore/stats.py
  - src/pagelore/write.py
---

## Cause

Agents paste real output into memory pages, including credentials that were
sitting in logs, `.env` dumps, or terminal scrollback. A memory store is meant
to outlive the session and gets indexed and searched, so a secret written into
it is worse than one left in a source file: it is now duplicated into a corpus
whose whole purpose is to be found.

## Exact formats refuse, entropy only warns

Two different mechanisms, on purpose. `find_secrets()` matches literal,
well-known credential shapes — AWS `AKIA[0-9A-Z]{16}`, GitHub `gh[ps]_...` and
`github_pat_...`, OpenAI `sk-...`, Anthropic `sk-ant-...`, Slack `xox[bpar]-...`,
and a PEM private-key header. Each of these formats was checked against an
authoritative source before being added — GitHub's own announcement for
`github_pat_`, Anthropic's admin API docs for the `sk-ant-api03-...` shape, and
gitleaks' default ruleset for Slack tokens and the PEM header — and only formats
that verified this way went in. A match refuses the write outright
(`secret_in_body`): the false-positive rate on an exact vendor-format string is
effectively zero, so there is nothing to weigh against refusing.

Every pattern except the PEM header also requires a left boundary
(`(?<![A-Za-z0-9_-])` before the match): without one, `sk-` and every other
prefix also matched mid-word, inside an ordinary kebab-case slug or wiki-link
— `risk-assessment-...` contains the literal substring `sk-assessment-...`,
`disk-image-...` contains `sk-image-...`, and both refused real writes before
this was caught in review. A real credential is never preceded by another
identifier character, so the boundary is exact, not a heuristic tradeoff.

`find_high_entropy()` instead flags any 40+ character run of
base64/hex-alphabet characters whose Shannon entropy is at or above 4.5
bits/symbol — the formula and threshold are carried over from the legacy
detector this replaces. This is deliberately non-fatal: a hash, a UUID string,
a base64-encoded blob, or a long opaque ID can all cross that threshold without
being a secret. A 40-character hex SHA cannot reach it (entropy tops out at
log2(16) = 4.0 bits/char over a 16-symbol alphabet), and ordinary long
identifiers (snake_case, English prose) stay well under it because real text
has skewed letter frequencies — but anything that reads as genuinely random
still deserves a second look, so it gets a `⚠` on stderr after a successful
write instead of blocking it.

Both checks scan `--title` and the incoming `--body` (not the page that
results from merging with what is already on disk) *separately*, each with its
own line numbering, and report a human-readable location: `title`, or
`body line N` where N counts only the `--body` text the agent actually typed.
An earlier version concatenated them as one `f"{title}\n{body}"` string before
scanning, which put every body line number one higher than what `--body`
itself contains — caught in review before release.

## Why the value is never logged

`reject()`'s `reason` argument is written verbatim to `.memory/.log.jsonl`
(see [[log-and-reader-ship-together]]). A gate whose refusal message repeats
the very value it is trying to keep out of the store would defeat its own
purpose the moment anyone read the log — and the log is read routinely, by
`lore stats` and by agents debugging a refusal. So the `secret_in_body` reason
carries only the kind (`aws_access_key`, `github_token`, ...) and the location
(`title` or `body line N`), never the match itself.

## Rejected alternative: a redacted prefix

An earlier version of this idea (informally, "show the first N characters so
the agent knows which line to fix") was rejected. For an AWS access key, which
is 20 characters total (`AKIA` + 16), a "redact everything after the prefix"
scheme that keeps even a modest-looking prefix (e.g. 12 characters) leaves only
8 characters hidden — 60% of the key would sit in stderr and in the log in
plain text. The line number alone is enough for an agent to find and remove the
value from its own output; the kind name is enough to know what it needs to
rotate. Neither needs the value itself.

## What `lore stats` had to learn

The log gets a new field, `warnings: [codes]`, written only when non-empty.
At the time this was written the only code was `high_entropy`; `dangling_link`
(see [[links-checked-not-refused]]) now shares the same field, so the two
codes can appear together on one write event. Per
[[log-and-reader-ship-together]], a log field ships with its reader in the
same change: `summarise()` in `stats.py` now returns `warn_codes`, grouped
exactly like `reject_codes` (a `Counter` over the codes seen across `write`
events, whatever they are), and the text output prints a `warned` line next to
the `refused` one.
