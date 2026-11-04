---
slug: panes-wide-char-input
title: "UTF-8 input was dropped byte by byte; wide chars are read with a timed drain"
kind: bug
created: 2026-09-21
updated: 2026-09-21
checked: 2026-11-04T15:26:26+00:00
sources:
  - src/pagelore/panes.py
  - tests/test_panes.py
---

## Cause

The panes field gated input on `32 <= key <= 126`, the ASCII band. Cyrillic
(and any multibyte UTF-8) reaches curses as one `getch` int per byte, all
≥ 128, so every Cyrillic keystroke was silently discarded — a real search
over a bilingual store could never be typed. A second latent bug rode along:
`field_insert` advanced the cursor by 1 no matter how many characters it
inserted.

## Fix

`_wide_char` assembles one character: read the lead byte (128–255), drain the
UTF-8 continuation bytes (0x80–0xBF) with a 30 ms window timeout — so the last
character of a burst decodes when the burst ends, not one keystroke later —
then restore blocking; a non-continuation byte is pushed back with
`ungetch`. The decoded letter is inserted through the same `field_insert` in
both the field and the picker (its filter reads the field). `field_insert`
now advances the cursor by `len(ch)`.

## Tests

`test_the_screen_draws_like_opencode_and_runs_commands` types a Cyrillic
query into the field left behind by a bare search and asserts it echoes and
runs; `wait_for` strips CSI sequences first, because ncurses can emit
erase-to-EOL between the bytes of one printed word. Unit coverage: a Cyrillic
query composes and runs.

[[panes-opencode-screen]]
