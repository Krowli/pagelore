---
slug: windows-liveness-probe-kills
title: "os.kill(pid, 0) is a liveness probe on POSIX and a kill on Windows"
kind: bug
created: 2026-08-18
updated: 2026-09-26
checked: 2026-11-04T15:26:47+00:00
sources:
  - src/pagelore/lib.py
  - tests/test_concurrency.py
---

## Cause

The per-page write lock decides that a lock is stale by asking whether the process
that took it still exists. The POSIX idiom for that question is `os.kill(pid, 0)`
— a signal of 0 performs the permission and existence checks and delivers nothing.

On Windows it is not a question at all. Python's documentation is explicit: any
signal other than `CTRL_C_EVENT` and `CTRL_BREAK_EVENT` is delivered by calling
`TerminateProcess`. So on every contended write, the probe killed the sibling
writer it was asking about — and then, finding the lock file still there, waited
the full timeout for a process it had itself just destroyed.

A second, quieter half: the host identity written into each lock came from
`os.uname()`, which does not exist on Windows. The `AttributeError` fallback wrote
`unknown-host` for every lock, so the hostname guard that exists to stop a PID from
another machine being trusted was comparing a constant to itself.

## How it surfaced

Not as data loss and not as a crash. CI hung: 21 tests passed on
windows-latest and the job was killed. Locally, on macOS, everything was green on
both retrieval paths — the whole class of bug is invisible on the machine it was
written on.

It was pushed before CI had run. The releases for 0.1.0 and 0.2.0 were already
published by the time the failure appeared, which is why 0.2.1 exists.

## Fix

Liveness goes through a platform check: `OpenProcess(SYNCHRONIZE)` on Windows,
distinguishing "no such process" (`ERROR_INVALID_PARAMETER`) from "access denied",
and returning *unknown* rather than a guess when the platform cannot answer — in
which case the mtime rule decides, as it did before any of this existed. The host
identity comes from `platform.node()`.

A test pins `os.kill` to that one guarded probe by reading the source, because the
behaviour it guards against cannot be reproduced on the machine most of this is
written on. See [[concurrent-writes-need-a-lock]].

## The replacement probe had its answer inverted

2026-09-26. `test_parallel_writes_to_one_slug_all_survive` failed intermittently on
windows-latest ("sections lost: [0, 3, 5]"). The Windows branch of `_process_alive`
answered `OpenProcess` failing with ERROR_INVALID_PARAMETER — no such process — by
returning `GetLastError() == 87`, which is True: alive. So a lock whose owner had
exited and been reaped was never taken over. The existing test missed it because it
asked about a child whose `Popen` still held a handle; a process somebody holds a
handle to still opens, the exit-code branch answered correctly, and the error branch
never ran. Now `_windows_process_alive` takes the API as arguments so a test decides
87 → dead, 5 (access denied) → alive, anything else → unknown on any OS, and it reads
the error through `WinDLL(use_last_error=True)` rather than a later `GetLastError`
call that ctypes itself may have clobbered. Full chain in
[[concurrent-writes-need-a-lock]].
