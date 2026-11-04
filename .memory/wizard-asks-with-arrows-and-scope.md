---
slug: wizard-asks-with-arrows-and-scope
title: "The wizard asks with arrows, and asks where it applies"
kind: decision
created: 2026-09-19
updated: 2026-11-04
checked: 2026-11-04T15:28:28+00:00
sources:
  - src/pagelore/init.py
  - src/pagelore/menu.py
---

## Context

The first person to run `lore init` typed a digit at a wall of text and asked why it
was not a normal menu with arrow keys like every other tool they use, and why
choosing "Claude Code" had written into their global config when they wanted one
project. Both questions were fair, and the second was not a preference: the wizard
offered three files, all of them global, and the screen said "applies to every
project" while giving no alternative. That is a notice, not a choice.

The honest part of the answer is that fifteen tests drove those questions and one pty
test proved they were asked at all. Every one of them checked whether the wizard did
the right thing. None of them looked at what using it was like, so "correct" shipped
and "usable" was never measured. [[installed-command-not-copied-directory]] records
the same shape of gap on the packaging side.

## Decision

The first question is scope (the wizard asks four questions now: [[mcp-offered-as-a-choice]]
added how the agent reaches the memory). "This project only" writes into that
repository's own `CLAUDE.md`, `GEMINI.md` or `AGENTS.md`; "every project" writes into
the home-directory ones as before. `--scope project` is the same answer for a script,
and it says so and falls back to the global files rather than guessing when there is no repository.

Arrows, space and enter, redrawn in place, on a terminal that can be put into raw
mode. Everywhere else — a pipe, a CI job, a test driving StringIO — the numbered
prompt stays exactly as it was. That split is not a concession: `lore init --agent
claude --yes` runs in scripts, and a wizard that stalls waiting for a keypress that
is never coming is worse than an ugly one. It is also why every existing test of
these questions kept working without being touched.

## The bug the pty test found

Raw mode was entered and left around each individual keypress, leaving the terminal
cooked in between. A key pressed in that window was echoed onto the screen as `^[[B`
and then thrown away, because `tty.setraw` defaults to `TCSAFLUSH`, which discards
queued input. The menu looked broken and then waited forever for a key the person had
already pressed. It reproduced every time under a pty, which types faster than anyone
can, and never once by hand.

Raw mode is now held for the whole question and entered before the question is
printed, which closes the window at both ends. Everything printed inside it carries
`\r\n`, because raw mode turns off the newline translation and a bare line feed walks
the list off to the right.

## Why key handling is a pure function

`menu.decode` takes bytes and returns a name. Terminal behaviour cannot be asserted
from a test with no terminal, and both arrow forms — `ESC [ A` and the application
cursor `ESC O A` — plus the Windows two-byte `\xe0 H` are just byte sequences. So the
table is tested directly and exhaustively, and the two pty tests are left to prove
only the wiring: that a real terminal gets the menu at all, and that a real arrow
moves the cursor.

## The screen, after the mechanics

Arrows shipped and the same person asked again, this time about the screen: no
colour, no weight, title and note and hint and rows in one block, columns that moved
between one question and the next, and every answered menu left standing under the
next one so nothing said which menu was live. All of it was the old numbered layout
with `❯` glued on; nothing had been designed, because every test measured whether
the wizard did the right thing and none looked at it.

Rendering is now three pure functions in `menu.py` — `render_question`,
`render_list`, `render_answer` — so the screen can be asserted line by line without a
terminal, and `ask` only writes what they return. Bold `? title`, dim note, blank
line, rows, blank line, dim key hint. The cursor row is cyan. `WIDTH` is one label
column for both menu shapes: in the tick-box list the `[ ] ` eats into the label
column instead of pushing the details four columns right.

An answered question collapses: cursor up over the whole block, erase to the end of
the screen, one line `✔ title  answer` (or `– title  skipped` on escape). The blank
line above the question is part of the erased block so that answered questions stack
with no gap; a text block printed between questions (`manual()`, the "start a new
session" line) ends with its own blank line to keep the gap on that side. That
convention is the one thing a future edit to `init.py`'s output is likely to break.

Colour is off under `NO_COLOR` or `TERM=dumb` and never sent to a pipe. The
numbered prompt for pipes and CI is untouched, which is why no existing test of the
questions changed except where a path is now shown as `~/…`. Paths on screen go
through `init.short()`, with one exception: the `+ @…` include line in the preview is
printed exactly as it will be written, because a preview that differs from the write
is not a preview.
