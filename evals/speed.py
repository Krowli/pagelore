#!/usr/bin/env python3
"""What a search costs, end to end, as the command a user types.

    python3 evals/speed.py                    # 90, 1000 and 5000 pages
    python3 evals/speed.py --pages 90 1000    # just those sizes

Two numbers per size, because they answer different questions. The **warm** one
is what a user waits for: the SQLite FTS5 index is built and the query hits it.
The **cold** one is the same search with the index refused, which is what happens
on a read-only checkout, on a Python without `sqlite3`, and while a sibling
process is rebuilding — so it is a real path, not a pessimistic hypothetical, and
it is the number that decides how large a store this design can carry.

Measured as separate processes, not as function calls in this one, because that is
the shape: one process per search, interpreter startup included. Nothing here is
imported from the package for timing; it spawns whatever `lore` the PATH resolves,
and reports which, since a console script and `python -m` are different numbers.

The corpus is the committed 90 pages, grown to a size by suffixing slugs. That
inflates vocabulary overlap, which makes the index look slightly better than a
store of genuinely distinct pages would — the ranking numbers in `run.py` are the
ones to trust about quality. This file is only about time.
"""
from __future__ import annotations

import argparse
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import run as harness  # noqa: E402

QUERY = ["terminal", "freeze", "webgl", "context", "lost"]
REPEATS = 7


def entry_point() -> tuple[list[str], str]:
    found = shutil.which("lore") or shutil.which("pagelore")
    if found:
        return [found], Path(found).name
    return [sys.executable, "-m", "pagelore"], "python -m pagelore"


def grown(pages: list[dict], target: int) -> list[dict]:
    out = []
    while len(out) < target:
        round_number = len(out) // len(pages)
        for page in pages:
            if len(out) >= target:
                break
            copy = dict(page)
            if round_number:
                copy["slug"] = f"{page['slug']}-{round_number}"
                copy["supersedes"] = []      # a copied supersedes would demote the original
            out.append(copy)
    return out


def median_ms(argv: list[str], env: dict) -> float:
    subprocess.run(argv, capture_output=True, env=env)           # warm the filesystem
    times = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        subprocess.run(argv, capture_output=True, check=True, env=env)
        times.append((time.perf_counter() - started) * 1000)
    return statistics.median(times)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pages", type=int, nargs="+", default=[90, 1000, 5000])
    args = ap.parse_args(argv)

    head, label = entry_point()
    corpus = harness.load_corpus()["pages"]
    print(f"{label}, python {'.'.join(map(str, sys.version_info[:3]))}, "
          f"median of {REPEATS} runs\n")
    print(f"{'pages':>7}  {'warm (index)':>13}  {'no index':>10}  {'ratio':>6}")
    print("-" * 42)

    for size in args.pages:
        with tempfile.TemporaryDirectory() as tmp:
            store = harness.materialise(grown(corpus, size), Path(tmp))
            search = [*head, "search", "--store", str(store), *QUERY]
            # A benchmark run is not a search an agent asked; it must not land in a
            # real project's log, so both arms turn logging off.
            warm_env = dict(os.environ, PAGELORE_NO_LOG="1")
            cold_env = dict(os.environ, PAGELORE_NO_FTS5="1", PAGELORE_NO_LOG="1")
            subprocess.run(search, capture_output=True, env=warm_env)   # build the index
            warm = median_ms(search, warm_env)
            cold = median_ms(search, cold_env)
        print(f"{size:>7}  {warm:>10.0f} ms  {cold:>7.0f} ms  {cold / warm:>5.1f}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
