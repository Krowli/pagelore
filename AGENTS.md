<!-- pagelore 0.8.2 — the block an agent reads every turn. Managed by `lore`: it is
     rewritten whenever the installed version changes, so edits here are lost. Put your
     own rules in the file that includes this one. Include it by path rather than copying
     it; a copy goes stale on the next release and nothing says so. -->

# Project memory

Durable decisions, contracts and bug post-mortems live as markdown pages in `.memory/`. Treat them as the record of why this project looks the way it does.

**Before stating anything about this project** — what it is, what it does, how a part of it works, why it is that way, what was decided or rejected — and before changing an unfamiliar subsystem, search first:

```bash
lore search "your query"
```

Open a full page with `lore show <slug>`. A hit marked `⚠ superseded by <slug>` was replaced — read the replacement first. Add `--touching <path>` to put the pages written against a file you are about to change first. If nothing relevant comes back, say so rather than guessing.

The trigger is the kind of claim you are about to make, not the wording of the question; "how does X work" and "what do you know about this project" are memory questions too.

This file is not a substitute for the search — it carries instructions rather than reasons, and it goes stale while a page stays dated and sourced.

Skip the search only for mechanical work (a command, a typo, a rename) and for general programming questions.

**After an architectural decision, a non-obvious bugfix, or a contract change**, write the page:

```bash
lore write --slug short-kebab-slug --title "One line" --kind decision \
  --source path/to/file --body -   <<'PMEOF'
## Cause

What a future agent could not reconstruct from the code...
PMEOF
```

`--kind` is one of `decision`, `bug`, `concept`, `howto`. The terminator is `PMEOF`, not `EOF`, so a page that documents heredocs cannot end its own body early. When a decision reverses an earlier one, add `--supersedes <old-slug>`: that stamps the old page and demotes it, instead of leaving two pages that both read as current.

The command validates and rejects: no sources, a source path that does not exist, a resulting page too short to be worth keeping. A rejection exits non-zero and prints a `FIX:` line with the command to run instead — follow it rather than writing the markdown file by hand.

Re-running the same slug replaces same-header sections in place and appends new ones, so amendments are cheap and safe.

Skip this for typos, reverts, formatting and test-only edits. Before you report the work done, ask whether it changed three or more files; if so, write the page or say in one line that there is nothing worth keeping. One topic per page; cross-link with `[[other-slug]]`.

`lore` is on PATH and works from any directory; `lore stats` says what the store has been doing. If the shell answers `lore: command not found`, the program is not on this shell's PATH — say so rather than writing pages by hand, because a page written around the command is skipped by search until someone rewrites it.
