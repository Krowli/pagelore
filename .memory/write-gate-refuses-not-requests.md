---
slug: write-gate-refuses-not-requests
title: "The write path refuses pages instead of asking for good ones"
kind: decision
created: 2026-08-17
updated: 2026-09-16
checked: 2026-11-04T15:26:47+00:00
sources:
  - src/pagelore/search.py
  - src/pagelore/write.py
---

## Context

The corpus this skill was designed against had 104 of 495 pages that were
auto-generated stubs, bodies around 139 characters, and they took the top two
result slots for real queries. The rules file asking the agent to keep the store
tidy was present the whole time. Asking did not work.

## Decision

The quality check lives in the write path, not in prose. A page with no source, a
source path that does not resolve, a body that leaves the page under 200
characters, an unknown kind or a non-kebab slug is refused: exit non-zero, plus a
`FIX:` line naming the exact next command. The correction then lands inside the
agent's own tool loop, where it acts on it, rather than in a document it may
never read.

## Consequences

Refusal codes are short stable tokens rather than prose so they can be counted: a
gate firing constantly on one code is either a real corpus problem or a rule that
needs loosening, and there is no way to tell which from memory.

The gate had an unguarded side door until a `PreToolUse` hook closed it: the
ordinary Write tool could create a page directly, so "writes are refused, not
requested" was itself a request. This project's own CLAUDE.md states the rule that
was being broken — prefer a hook over prose for anything that must hold.
`PROJECT_MEMORY_ALLOW_HAND_EDIT=1` is the deliberate escape hatch, checkable in a
way a promise in prose is not.

## The side door, after the hook

The `PreToolUse` hook that closed the side door existed on Claude Code only, and
the skill claims to work on any agent, so it is gone — see
[[scripts-carry-the-contract-not-hooks]]. The door is closed from the other
side now: `memory_search.py` applies the same floor on read. A page under
MIN_BODY that matched the query is not ranked and is named, so it can be
rewritten through the script; a page with no sources is shown but marked. The
stubs this decision was written against would be skipped rather than sit in the
top two slots, on every harness, because search runs on every harness.
