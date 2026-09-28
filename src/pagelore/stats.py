#!/usr/bin/env python3
"""Summarise the store's log: what was written, what was refused, what was asked.

Usage:  lore stats [--store DIR] [--since YYYY-MM-DD] [--json]

Exists because a log nobody reads is the same failure as no log. Four questions
it answers, which are exactly the ones a trial period has to settle:

  did agents write at all          — writes, and how many were merges
  is the gate helping or annoying  — refusals by code, as a share of attempts
  does search find things          — queries that returned nothing
  did a session that read the memory write anything — by the session id in each line

A refusal rate that is high and concentrated on one code usually means the rule
is wrong, not the writer. Queries with zero hits are the strongest signal there
is: either the corpus has a hole, or ranking does.

Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from collections import Counter, deque
from pathlib import Path

from .cli import add_version
from .lib import LOG_NAME, find_store

# A search counts as a repeat when the same session asked again within this many
# seconds and got back the same top page — the paraphrase-and-reask pattern real
# logs showed, where an agent re-searches instead of trusting the answer it
# already had. Two minutes, not a shorter window: the point is catching a
# rephrase after the agent read the first result and judged it insufficient,
# not catching a double-submit.
REPEAT_WINDOW_SECONDS = 120.0


def read_log(store: Path, since: str | None) -> list[dict]:
    path = store / LOG_NAME
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line should not hide the rest of the log
        if not isinstance(rec, dict) or "ts" not in rec:
            continue  # nor should a line from some other writer
        if since and rec.get("ts", "") < since:
            continue
        out.append(rec)
    return out


def _median(values: list[int]) -> int:
    """The real median. The upper-middle value was reported for even counts, which
    biased high exactly the statistic used to argue about the length floor."""
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _repeated_searches(searches: list[dict]) -> int:
    """Count of searches this log's `repeated` line reports.

    Grouped by session — except that every record with NO session is grouped
    together into one shared stream, rather than being skipped. That is not a
    loosening for its own sake: `lore mcp` runs as a long-lived server process
    that never sees `$CLAUDE_CODE_SESSION_ID` (the harness exports it to the
    shell the Bash tool runs in, not to a stdio server it spawns once), so
    every MCP search is session-less — and a real log showed exactly this
    stream carrying five rewordings of one question, four of them repeats,
    that the session-keyed version reported as zero. A log line from before
    `session` shipped at all falls into the same bucket, for the same reason.
    The 120-second window keeps the false-positive cost low: two genuinely
    different agents landing on the same top page for unrelated queries
    within two minutes of each other is rare, and missing the real,
    overwhelmingly common case (a session-less majority) is the worse failure
    of the two.

    Records are chronological, so per stream this keeps only what is still
    inside the window instead of an ever-growing list scanned with `any()` on
    every record — that was O(n) per record (O(n²) overall) and made a large
    session-less MCP-only log slow: 20 000 same-top session-less records took
    14s before this, well under a second after. A `deque` holds each stream's
    entries in arrival order so the ones that have aged out of the window can
    be popped off the left in O(1); a parallel `Counter` of tops still in the
    window turns "does some earlier entry in the window share this top" into
    an O(1) lookup instead of a scan. Each entry is pushed and popped at most
    once, so the whole pass is O(n).
    """
    windows: dict[str | None, deque[tuple[float, str]]] = {}
    top_counts: dict[str | None, Counter] = {}
    repeated = 0
    for r in searches:
        try:
            ts = _dt.datetime.fromisoformat(r["ts"]).timestamp()
        except (KeyError, ValueError):
            continue  # an unparseable ts can neither match nor be matched
        top = r.get("top")
        if top is None:
            continue  # a null top can never match, so it is not worth tracking
        stream = r.get("session")  # None is its own stream: every session-less record shares it
        window = windows.setdefault(stream, deque())
        counts = top_counts.setdefault(stream, Counter())
        cutoff = ts - REPEAT_WINDOW_SECONDS
        while window and window[0][0] < cutoff:
            _, old_top = window.popleft()
            counts[old_top] -= 1
            if counts[old_top] <= 0:
                del counts[old_top]
        if counts.get(top, 0) > 0:
            repeated += 1
        window.append((ts, top))
        counts[top] += 1
    return repeated


def summarise(records: list[dict]) -> dict:
    writes = [r for r in records if r.get("event") == "write"]
    rejects = [r for r in records if r.get("event") == "reject"]
    searches = [r for r in records if r.get("event") == "search"]
    attempts = len(writes) + len(rejects)
    misses = [r for r in searches if not r.get("hits")]

    # `touched` is only on records that passed `--touching`, and only from the
    # point this field shipped. `touching_searches` counts every one of those
    # (old and new); `touching_measured` is the slice that can actually be
    # judged. The miss rate is read against `measured`, never against
    # `touching_searches` — a log spanning the field's introduction otherwise
    # makes a handful of measured misses look diluted by every old, unmeasurable
    # line (e.g. 1 miss in 3 measured reads as "2%" if divided by 47 total).
    touching_searches = [r for r in searches if "touching" in r]
    touching_measured = [r for r in touching_searches if "touched" in r]
    touching_misses = [r for r in touching_measured if r.get("touched") == 0]

    # A session is whatever the harness stamped as one; lines without a stamp
    # are another harness or an older log, and are not a session. The number to
    # watch is sessions that searched and never wrote — the write side's "did it
    # happen", collected by the scripts themselves rather than by a hook.
    sessions = {r["session"] for r in records if r.get("session")}
    searched = {r["session"] for r in searches if r.get("session")}
    wrote = {r["session"] for r in writes if r.get("session")}
    unrecorded = len(searched - wrote)
    attributed = sum(1 for r in writes if r.get("session"))

    # `via` shipped after `search`/`reject` did, so a log spanning its
    # introduction mixes lines that carry it with lines that cannot. Reporting
    # "unknown" only makes sense once something to contrast it with exists —
    # an old log with no `via` anywhere should read as "nothing to report", not
    # as "everything is unknown".
    with_via = [r for r in searches if "via" in r]
    if with_via:
        via_counts = Counter(r.get("via", "unknown") for r in searches)
        via_order = [k for k in ("cli", "mcp") if k in via_counts]
        via_order += sorted(k for k in via_counts if k not in ("cli", "mcp", "unknown"))
        if "unknown" in via_counts:
            via_order.append("unknown")
        searches_by_via = {k: via_counts[k] for k in via_order}
    else:
        searches_by_via = {}

    repeated = _repeated_searches(searches)

    return {
        "span": [records[0]["ts"], records[-1]["ts"]] if records else [],
        "writes": len(writes),
        "creates": sum(1 for r in writes if r.get("mode") == "create"),
        "merges": sum(1 for r in writes if r.get("mode") == "merge"),
        "unchanged": sum(1 for r in writes if r.get("mode") == "unchanged"),
        "median_chars": _median([r.get("chars", 0) for r in writes]),
        "rejects": len(rejects),
        "reject_rate": round(len(rejects) / attempts, 3) if attempts else 0.0,
        "reject_codes": dict(Counter(r.get("code", "?") for r in rejects).most_common()),
        # Shaped exactly like reject_codes: a code that fires constantly is
        # either a real corpus problem or a rule to loosen, and that is not
        # visible from the per-line ⚠ text alone.
        "warn_codes": dict(Counter(
            code for r in writes for code in r.get("warnings", [])).most_common()),
        "searches": len(searches),
        "zero_hit_searches": len(misses),
        "zero_hit_rate": round(len(misses) / len(searches), 3) if searches else 0.0,
        "zero_hit_queries": [r.get("query") for r in misses][-15:],
        "touching_searches": len(touching_searches),
        "touching_measured": len(touching_measured),
        "touching_misses": len(touching_misses),
        "touching_miss_paths": [r.get("touching") for r in touching_misses][-15:],
        "sessions": len(sessions),
        "sessions_unrecorded": unrecorded,
        "writes_per_session": round(attributed / len(sessions), 3) if sessions else 0.0,
        "searches_by_via": searches_by_via,
        "repeated_searches": repeated,
        "repeated_rate": round(repeated / len(searches), 3) if searches else 0.0,
    }


def main(argv: list[str] | None = None, *, prog: str = "lore stats") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Summarise the memory log.")
    add_version(ap)
    ap.add_argument("--store", type=Path, default=None)
    ap.add_argument("--since", default=None, help="ISO date, e.g. 2026-08-09")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    store = args.store or find_store()
    records = read_log(store, args.since)
    if not records:
        print(f"no log entries in {store / LOG_NAME}", file=sys.stderr)
        return 0

    s = summarise(records)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    print(f"{s['span'][0]} … {s['span'][1]}\n")
    print(f"writes    {s['writes']:>5}   ({s['creates']} new, {s['merges']} merged, "
          f"{s['unchanged']} unchanged, median {s['median_chars']} chars)")
    print(f"refused   {s['rejects']:>5}   ({s['reject_rate']:.0%} of write attempts)")
    for code, n in s["reject_codes"].items():
        print(f"            {n:>3}  {code}")
    if s["warn_codes"]:
        print(f"warned    {sum(s['warn_codes'].values()):>5}   "
              f"({', '.join(f'{code}:{n}' for code, n in s['warn_codes'].items())})")
    print(f"searches  {s['searches']:>5}   ({s['zero_hit_rate']:.0%} returned nothing)")
    if s["searches_by_via"]:
        print(f"            via: {', '.join(f'{via} {n}' for via, n in s['searches_by_via'].items())}")
    for q in s["zero_hit_queries"]:
        print(f"            miss: {q}")
    if s["searches"]:
        print(f"repeated  {s['repeated_searches']:>5}   ({s['repeated_rate']:.0%} of searches "
              f"re-returned a top page seen within the previous 2 minutes)")
    if s["touching_searches"]:
        print(f"touching  {s['touching_searches']:>5}   ({s['touching_measured']} measured, "
              f"{s['touching_misses']} found no page touching the path)")
        for paths in s["touching_miss_paths"]:
            print(f"            miss: {', '.join(paths)}")
    print(f"sessions  {s['sessions']:>5}   ({s['sessions_unrecorded']} searched and never "
          f"wrote, {s['writes_per_session']:.2f} writes per session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
