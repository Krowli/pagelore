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
import json
import sys
from collections import Counter
from pathlib import Path

from .cli import add_version
from .lib import LOG_NAME, find_store


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


def summarise(records: list[dict]) -> dict:
    writes = [r for r in records if r.get("event") == "write"]
    rejects = [r for r in records if r.get("event") == "reject"]
    searches = [r for r in records if r.get("event") == "search"]
    attempts = len(writes) + len(rejects)
    misses = [r for r in searches if not r.get("hits")]

    # A session is whatever the harness stamped as one; lines without a stamp
    # are another harness or an older log, and are not a session. The number to
    # watch is sessions that searched and never wrote — the write side's "did it
    # happen", collected by the scripts themselves rather than by a hook.
    sessions = {r["session"] for r in records if r.get("session")}
    searched = {r["session"] for r in searches if r.get("session")}
    wrote = {r["session"] for r in writes if r.get("session")}
    unrecorded = len(searched - wrote)
    attributed = sum(1 for r in writes if r.get("session"))

    return {
        "span": [records[0]["ts"], records[-1]["ts"]] if records else [],
        "writes": len(writes),
        "creates": sum(1 for r in writes if r.get("mode") == "create"),
        "merges": sum(1 for r in writes if r.get("mode") == "merge"),
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
        "sessions": len(sessions),
        "sessions_unrecorded": unrecorded,
        "writes_per_session": round(attributed / len(sessions), 3) if sessions else 0.0,
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
          f"median {s['median_chars']} chars)")
    print(f"refused   {s['rejects']:>5}   ({s['reject_rate']:.0%} of write attempts)")
    for code, n in s["reject_codes"].items():
        print(f"            {n:>3}  {code}")
    if s["warn_codes"]:
        print(f"warned    {sum(s['warn_codes'].values()):>5}   "
              f"({', '.join(f'{code}:{n}' for code, n in s['warn_codes'].items())})")
    print(f"searches  {s['searches']:>5}   ({s['zero_hit_rate']:.0%} returned nothing)")
    for q in s["zero_hit_queries"]:
        print(f"            miss: {q}")
    print(f"sessions  {s['sessions']:>5}   ({s['sessions_unrecorded']} searched and never "
          f"wrote, {s['writes_per_session']:.2f} writes per session)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
