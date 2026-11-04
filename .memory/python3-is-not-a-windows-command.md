---
slug: python3-is-not-a-windows-command
title: "The hooks were registered as python3, which Windows does not have"
kind: bug
created: 2026-08-18
updated: 2026-11-04
checked: 2026-11-04T15:30:10+00:00
sources:
  - install.sh
  - npm/bin/lore.js
---

## Cause

Both hooks were registered with the command `python3 <script>`. On Windows that
command does not exist: the installer puts `python`, `py` and `pymanager` on PATH,
and `python3` only as an optional versioned alias such as `python3.14.exe` in a
separate directory.

So on Windows both hooks silently failed to start. The agent was never told the
project had a memory, and the `PreToolUse` guard blocked nothing — which is exactly
the hole that guard exists to close. Nothing errored; a hook that cannot launch
simply produces no output.

There is an irony worth keeping: `session_start.py` justifies being written in
Python rather than bash on the grounds that it "behaves the same on Linux, macOS
and Windows, where a bash hook needs a .cmd shim beside it". The script does. The
name you invoke it by does not.

## Why the suite could not catch it

Two layers of masking, and both were of our own making.

Every hook test ran the script through `sys.executable`, never through the string
that is actually configured — so the tests proved the script works, which was never
in doubt, and said nothing about whether it would be launched. And on CI,
`actions/setup-python` puts a `python3` shim on Windows runners, so even an
end-to-end check there would have passed for a reason that does not hold on a
user's machine.

## Fix

`install.sh` resolves an interpreter — `python3`, then `python`, then `py -3`, each
probed for 3.11+ rather than mere existence — and writes the one that worked into
`settings.json`. `--interpreter` forces a choice. The version probe caught a second
thing on the way: the old check accepted any `python3`, and on macOS that is
`/usr/bin/python3`, which is 3.9.

A test now reads the command out of the generated `settings.json` and runs it
through a shell, which is the only way this class of bug is visible at all.

`hooks/hooks.json` cannot branch per platform, so the plugin install still
hard-codes one name. That is a real limitation and it is documented rather than
hidden. See [[windows-liveness-probe-kills]].

## Since 0.4.0

The fix above is history:

- The hooks are gone ([[scripts-carry-the-contract-not-hooks]]), and `hooks/hooks.json` no longer exists.
- `install.sh` no longer installs anything ([[installed-command-not-copied-directory]]).

The lesson survived in the npm launcher, `npm/bin/lore.js`, because Windows has no `python3`:

| Platform | Interpreters tried, in order |
|---|---|
| Windows | `py -3`, `python`, `python3` |
| elsewhere | `python3`, `python` |

Each candidate is checked against the 3.9 floor, and the launcher fails with a `FIX:` line when none qualifies.

The pip and pipx routes need no interpreter name: their `lore` console script is generated for the interpreter that installed it.
