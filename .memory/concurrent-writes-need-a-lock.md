---
slug: concurrent-writes-need-a-lock
title: "Two agents on one slug silently lost each other's sections"
kind: bug
created: 2026-08-17
updated: 2026-09-26
checked: 2026-11-04T15:26:46+00:00
sources:
  - src/pagelore/lib.py
  - src/pagelore/write.py
  - tests/test_concurrency.py
---

## Cause

A write parses the page, merges in memory and rewrites the whole file. There was
no lock, no `O_EXCL` and no re-read before writing, so a writer that finished
between another writer's parse and write was overwritten entirely. Both commands
exited 0.

Measured with twelve to twenty unmodified `memory_write.py` subprocesses writing
distinct sections of the same slug, with no instrumentation and no artificial
window: five runs lost 1, 1, 16, 0 and 1 of 20 sections. Subagent fan-out makes
this ordinary rather than exotic — several agents finish related work at the same
time and record it against the same page.

Rewriting in place also truncated the file first, so a concurrent search could
parse a half-written page and rank the fragment as the page's real content, and a
crash in that window left the page permanently short with no backup.

## Fix

An advisory lock file per page, taken with `O_CREAT|O_EXCL`, and the content
replaced through a temp file plus `os.replace` so a reader never sees a partial
page. The lock is self-healing: one older than 30 seconds is assumed to belong to
a dead process, and after 10 seconds the write proceeds regardless. Losing a
section is bad; refusing to record anything because of a stale file on disk is
worse.

The log is appended with one `O_APPEND` `os.write` per line, so parallel writers
cannot interleave halves of two records into one unparseable line.

## What the lock still did not cover

The per-page lock is advisory on purpose: after `LOCK_TIMEOUT_SECONDS` a writer
proceeds without it, because losing a section is bad and refusing to record anything
is worse. That leaves one window, and on 2026-09-19 a Windows CI runner found it.
Twelve writers on one slug, which is what subagent fan-out produces, and section 00
vanished while every one of the twelve commands exited 0. The exact failure this page
was written about, returning through the escape hatch built into its own fix.

Two causes, both of them a number tuned on the wrong machine.

The timeout was ten seconds, chosen against a fast POSIX filesystem. A dead holder is
already handled at once and separately by `_owner_is_gone`, so the timeout only ever
has to cover a holder that is alive and slow. Twelve Windows processes, each paying
interpreter startup and a virus scanner per file write, ran past ten seconds. It is
now sixty, which costs nothing when there is no contention.

And the escape hatch itself never checked its own work. An unlocked write now re-reads
the page afterwards, and if its own `## ` headers are not there it merges and writes
again, three times at most. Three because each attempt is a full read-merge-write and
the case it covers is already a writer that could not get a lock for a minute; looping
past that trades a possible lost section for a command that never returns.

## The scratch file was named by pid alone

Found while writing the test for the above. `atomic_write` built its temporary file as
`.<page>.<pid>.tmp`, so two threads in one process picked the same name and each
deleted or replaced the other's — `os.replace` then raised FileNotFoundError on a file
that had existed a moment earlier. One process per write is the shipped shape, so this
never fired in production, but `write_page` is importable and `evals/mcp_probe.py`
calls it directly. The name now carries the thread id too.

## The Windows loss on 2026-09-26, found by tracing rather than by tuning

The section above raised the timeout from ten seconds to sixty. The test still lost
sections on windows-latest a week later, so this time the lock was traced on the
runner — every takeover, failed delete and unlocked write printed to stderr, the
12-writer test shape run 50 times (CI run 36260115644, Python 3.11: 3 of 50
iterations lost sections, and 1 of 50 plain pytest runs). Every failing iteration
had the same chain:

1. The holder closed its lock and `unlink` raised PermissionError — "being used by
   another process". A waiter was reading the pid out of the lock in
   `_owner_is_gone`, and Windows will not delete a file another process has open
   without FILE_SHARE_DELETE. `__exit__` swallowed that and left the lock behind.
2. The holder exited, and its lock should have been taken over at once. It was not:
   `_process_alive` returned *alive* for a process that no longer exists (see
   [[windows-liveness-probe-kills]]).
3. So every other writer waited out the full sixty seconds, all timed out within the
   same 200 ms, and all wrote unlocked together. The escape hatch's re-read checks a
   writer's own headers, which each of them found, so each returned 0 over a page
   that had lost someone else's section.

Sixty seconds did not help because the wait was never slow work; it was a lock no
one would ever release. Fixed at both ends: the release retries a refused delete
for up to `REPLACE_TIMEOUT_SECONDS` (the reader holds the file for microseconds),
and the probe answers "no such process" with dead. Neither is a retry of the write
itself.

That fix still lost one iteration in 50 untraced (run 36261446128, Python 3.13). The
third hole: while a lock file is being deleted, Windows refuses to create one at the
same path with "access denied", not "exists". `page_lock` read any error but
`FileExistsError` as "this store cannot be locked" and wrote unlocked at once — in
the middle of the write whose release it had just watched begin. It now waits, as
for an existing lock, unless the directory really is not writable. Traced from
outside the code this time (a wrapper around `os.open` and `page_lock`): the refusal
fired 5 times in 200 iterations, and every one of them used to be an unlocked write.

After all three: run 36261633399, 100 iterations of twelve writers on each of Python
3.11 and 3.13 with no lost section and no unlocked write, and the plain test 50 of 50
on each.

Still open, and not what failed here: the unlocked escape hatch cannot see a section
it overwrote that was someone else's, and two waiters that both judge a dead owner
gone can race on the takeover: the second one deletes whatever lock is there by
then, which may be the first one's new, live lock. On Windows the new holder's open
handle refuses that delete — the traced run recorded it 51 to 72 times per 50
iterations, every one refused. POSIX has no such refusal; it has not been seen to
fire there, but nothing stops it.
