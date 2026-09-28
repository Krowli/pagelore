"""The CI gate on retrieval quality: `evals/run.py` measures it, but a number
nobody checks is a number that regresses unnoticed. This runs the same
evaluation in-process — no subprocess, no full method table, see below — and
fails the build if the shipped ranker moved backward by more than the noise
floor `evals/baseline.json` was frozen against.

Only the two shipped methods are run, not the whole comparison table in
`evals/run.py` (term-count, raw FTS5, grep): those are read by a person
deciding whether to change the ranker, not by CI on every push, and running
them here would triple the cost of every test job for numbers nothing acts on.

**Two runs, two baselines.** This suite runs twice in CI — once with the SQLite
FTS5 index available, once with `PAGELORE_NO_FTS5=1` (`.github/workflows/test.yml`,
"fallback, index disabled"). Under that variable, `shipped (fts5 index)` and
`shipped fallback (scan)` are the same code path (`methods.py`: `shipped()` calls
`memory_search.search()`, which itself falls back to the scan ranker whenever
`PAGELORE_NO_FTS5` is set — `fallback_scan()` just forces that unconditionally),
so comparing both against the FTS5-mode numbers would fail on every fallback run
for a ranking that never changed. `evals/baseline.json` therefore keeps two
sections, `fts5` and `scan`; which one a method's live numbers are checked
against is picked from the same environment variable the shipped code itself
reads, not guessed from which numbers happen to be smaller.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))

import run as evals_run  # noqa: E402
from methods import METHODS  # noqa: E402

from pagelore.index import DISABLE_ENV  # noqa: E402
from pagelore.lib import env as pagelore_env  # noqa: E402

BASELINE = json.loads((REPO / "evals" / "baseline.json").read_text(encoding="utf-8"))

# How far a metric may fall (rise, for `answered_anyway`, where lower is better)
# below its frozen value before this is a regression rather than run-to-run
# noise. Matches the margin `evals/baseline.json` documents.
TOLERANCE = 0.005

Row = tuple[str, float, float, bool]  # name, baseline, live, higher_is_worse


def _quality_rows(prefix: str, baseline: dict, known_item: dict, ambiguous: dict,
                  unanswerable: dict) -> list[Row]:
    rows: list[Row] = [
        (f"{prefix}: known_item ndcg@10", baseline["known_item"]["ndcg@10"],
         known_item["ndcg@10"], False),
        (f"{prefix}: known_item mrr@10", baseline["known_item"]["mrr@10"],
         known_item["mrr@10"], False),
        (f"{prefix}: known_item recall@1", baseline["known_item"]["recall@1"],
         known_item["recall@1"], False),
        (f"{prefix}: known_item recall@3", baseline["known_item"]["recall@3"],
         known_item["recall@3"], False),
    ]
    for query_type in sorted(baseline["known_item"]["by_type"]):
        rows.append((f"{prefix}: known_item by_type {query_type}",
                     baseline["known_item"]["by_type"][query_type],
                     known_item["by_type"].get(query_type, 0.0), False))
    rows.append((f"{prefix}: ambiguous ndcg@10", baseline["ambiguous_ndcg@10"],
                 ambiguous["ndcg@10"], False))
    rows.append((f"{prefix}: unanswerable answered_anyway",
                 baseline["unanswerable_answered_anyway"],
                 unanswerable["answered_anyway"], True))
    return rows


def _touching_rows(prefix: str, baseline: dict, live: dict) -> list[Row]:
    return [(f"{prefix}: touching {metric}", baseline[metric], live[metric], False)
            for metric in ("ndcg@10", "mrr@10", "recall@1", "recall@3")]


def test_retrieval_quality_has_not_regressed():
    # The same check `memory_search`/`index.py` make: PAGELORE_NO_FTS5 (or the
    # pre-0.6.0 PROJECT_MEMORY_NO_FTS5), read through the library's own `env()`
    # so this asks the question the shipped code actually answers, not a copy
    # of it that could drift.
    no_fts5 = bool(pagelore_env(DISABLE_ENV))

    if no_fts5:
        # See the module docstring: under this variable the two shipped methods
        # are the identical code path, so only one is run — computed once, used
        # for both — and both are checked against the one `scan` baseline.
        results = evals_run.compute({"shipped fallback (scan)": METHODS["shipped fallback (scan)"]})
        live = {"shipped (fts5 index)": results["shipped fallback (scan)"],
               "shipped fallback (scan)": results["shipped fallback (scan)"]}
        baseline_methods = {"shipped (fts5 index)": BASELINE["scan"]["shipped fallback (scan)"],
                           "shipped fallback (scan)": BASELINE["scan"]["shipped fallback (scan)"]}
        baseline_touch = BASELINE["scan"]["touching_shipped"]
    else:
        both = {name: METHODS[name] for name in
                ("shipped (fts5 index)", "shipped fallback (scan)")}
        results = evals_run.compute(both)
        live = results
        baseline_methods = {"shipped (fts5 index)": BASELINE["fts5"]["shipped (fts5 index)"],
                           "shipped fallback (scan)": BASELINE["fts5"]["shipped fallback (scan)"]}
        baseline_touch = BASELINE["fts5"]["touching_shipped"]

    rows: list[Row] = []
    for name in ("shipped (fts5 index)", "shipped fallback (scan)"):
        rows += _quality_rows(name, baseline_methods[name], live[name]["known_item"],
                              live[name]["ambiguous"], live[name]["unanswerable"])
    live_touch = results["_touching"]["methods"]["path as text query"]
    rows += _touching_rows("touching (path as text query)", baseline_touch, live_touch)

    lines = [f"{'metric':50} {'baseline':>10} {'now':>10} {'delta':>10}",
            "-" * 82]
    regressions = []
    for metric_name, baseline_value, live_value, higher_is_worse in rows:
        delta = live_value - baseline_value
        lines.append(f"{metric_name:50} {baseline_value:>10.4f} {live_value:>10.4f} {delta:>+10.4f}")
        regressed = delta > TOLERANCE if higher_is_worse else delta < -TOLERANCE
        if regressed:
            regressions.append(metric_name)

    table = "\n".join(lines)
    print("\n" + table)
    assert not regressions, (
        f"regressed by more than {TOLERANCE} vs evals/baseline.json: {regressions}\n\n{table}")
