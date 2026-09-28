#!/usr/bin/env python3
"""Measure retrieval quality on a fixed corpus and query set.

    python3 evals/run.py            # the table
    python3 evals/run.py --json     # machine-readable
    python3 evals/run.py --by-type  # broken down by query type

Everything it needs is in this directory and committed: the corpus, the queries,
and the methods. That is the point — `references/retrieval.md` used to argue the
design from numbers whose inputs were in nobody's repository, so no reader could
check them and no change could be re-measured.

What is measured
----------------
Known-item retrieval: each query has exactly one page it was written for, and the
question is where that page lands. Plus two sets that catch what known-item
retrieval cannot:

  ambiguous     several pages are legitimately relevant; measures whether the best
                one is first, not merely whether something was found
  unanswerable  no page answers it; measures false confidence, which is the failure
                mode a ranked list encourages

Confidence intervals are bootstrap over queries, 1000 resamples, so a difference
smaller than the interval is not a difference.

What this cannot tell you
-------------------------
The corpus and the queries were written by a language model, not harvested from a
real store. The paraphrase query type exists to fight the obvious bias — a query
written from a page tends to reuse its words, which flatters lexical search — but
it does not remove it. Read the per-type table, not the average. See README.md.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from methods import METHODS, TOUCHING_METHODS  # noqa: E402

BOOTSTRAP = 1000
SEED = 20260817


def load_corpus() -> dict:
    return json.loads((HERE / "corpus.json").read_text(encoding="utf-8"))


def materialise(corpus: list[dict], directory: Path) -> Path:
    """Write the corpus out as a real store, through the real writer."""
    sys.path.insert(0, str(HERE.parent / "src"))
    from pagelore import write as memory_write

    store = directory / ".memory"
    store.mkdir(parents=True, exist_ok=True)
    (store / ".tracked").write_text("evaluation corpus\n", encoding="utf-8")
    for page in corpus:
        memory_write.write_page(store, page["slug"], page["title"], page["kind"],
                                page.get("sources") or [], page["body"])
    for page in corpus:
        if page.get("supersedes"):
            memory_write.stamp_superseded(store, page["supersedes"], page["slug"])
    return store


def dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ranked: list[str], relevant: set[str], k: int = 10) -> float:
    gains = [1.0 if slug in relevant else 0.0 for slug in ranked[:k]]
    ideal = [1.0] * min(len(relevant), k)
    best = dcg(ideal)
    return dcg(gains) / best if best else 0.0


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for i, slug in enumerate(ranked):
        if slug in relevant:
            return 1.0 / (i + 1)
    return 0.0


def recall_at(ranked: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(s in relevant for s in ranked[:k]) else 0.0


def bootstrap_ci(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(SEED)
    n = len(values)
    means = []
    for _ in range(BOOTSTRAP):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return (means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1])


def evaluate(method, corpus, store, queries, *, return_ndcg: bool = False) -> dict:
    per_query = {"ndcg": [], "mrr": [], "r1": [], "r3": []}
    by_type: dict[str, list[float]] = {}
    for item in queries:
        ranked = method(item["q"], corpus, store)
        relevant = set(item["relevant"])
        n = ndcg_at(ranked, relevant)
        per_query["ndcg"].append(n)
        per_query["mrr"].append(reciprocal_rank(ranked, relevant))
        per_query["r1"].append(recall_at(ranked, relevant, 1))
        per_query["r3"].append(recall_at(ranked, relevant, 3))
        by_type.setdefault(item.get("type", "other"), []).append(n)

    low, high = bootstrap_ci(per_query["ndcg"])
    result = {
        "ndcg@10": statistics.fmean(per_query["ndcg"]),
        "ci": [low, high],
        "mrr@10": statistics.fmean(per_query["mrr"]),
        "recall@1": statistics.fmean(per_query["r1"]),
        "recall@3": statistics.fmean(per_query["r3"]),
        "by_type": {k: statistics.fmean(v) for k, v in sorted(by_type.items())},
        "n": len(queries),
    }
    if return_ndcg:
        # `compute()` builds the `_deltas` paired bootstrap from this instead of
        # running every method over `known` a second time, which used to double
        # the cost of the scan methods (no index, ~28 ms/query) for no new
        # information. Not part of the return value otherwise, so every existing
        # caller and the printed/JSON output are unchanged.
        result["_ndcg_values"] = per_query["ndcg"]
    return result


def paired_delta(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """Bootstrap over per-query differences, not over two independent means.

    Comparing two overlapping confidence intervals is the wrong test and hides
    real differences: every method here sees the same queries, so the difference
    is paired and the interval on it is much tighter.
    """
    diffs = [x - y for x, y in zip(a, b)]
    rng = random.Random(SEED)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(BOOTSTRAP))
    return (statistics.fmean(diffs), means[int(0.025 * BOOTSTRAP)],
            means[int(0.975 * BOOTSTRAP) - 1])


def calibration(corpus, store, known, unanswerable) -> dict:
    """Can anything in a result tell "there is an answer" from "there is not"?

    The answer measured here is no, and it is the most useful thing this harness
    has produced. Unanswerable queries are on-topic questions about the same
    project, so they share vocabulary with the corpus and score exactly like
    answerable ones. A score threshold — the obvious fix, and the one an audit
    recommended — costs recall and buys nothing.
    """
    sys.path.insert(0, str(HERE.parent / "src"))
    from pagelore import search as memory_search

    def top(query):
        hits = memory_search.search(query, store, k=1)
        if not hits:
            return 0.0, 0.0
        score, page = hits[0]
        terms = set(memory_search.tokenize(query))
        have = set(memory_search.tokenize(f"{page.title} {page.slug} {page.body}"))
        return score, (len(terms & have) / len(terms) if terms else 0.0)

    answerable = [top(q["q"]) for q in known]
    missing = [top(q) for q in unanswerable]
    return {
        "score": {
            "answerable_median": statistics.median(s for s, _ in answerable),
            "unanswerable_median": statistics.median(s for s, _ in missing),
        },
        "coverage": {
            "answerable_median": statistics.median(c for _, c in answerable),
            "unanswerable_median": statistics.median(c for _, c in missing),
        },
    }


def evaluate_unanswerable(method, corpus, store, queries) -> dict:
    """A query nothing answers should return nothing. Returning a confident-looking
    list instead is the failure a ranked interface invites."""
    returned_any = [1.0 if method(q, corpus, store) else 0.0 for q in queries]
    return {"answered_anyway": statistics.fmean(returned_any) if returned_any else 0.0,
            "n": len(queries)}


def compute(methods: dict | None = None) -> dict:
    """Run the full evaluation and return the same dict `--json` prints.

    `methods` restricts the main comparison table (default: every entry in
    `METHODS`) — the two shipped rows are enough for the CI gate in
    `tests/test_evals_baseline.py`, and skipping the rest is most of the cost
    of a full run. `_touching` always runs both `TOUCHING_METHODS`: it is
    already just the two, and the baseline needs its shipped row regardless
    of which `methods` were asked for.
    """
    methods = METHODS if methods is None else methods
    data = load_corpus()
    corpus = data["pages"]
    known = data["known_item"]
    ambiguous = data["ambiguous"]
    unanswerable = data["unanswerable"]
    touching = data.get("touching", [])

    with tempfile.TemporaryDirectory() as tmp:
        store = materialise(corpus, Path(tmp))
        results = {}
        per_query = {}
        for name, method in methods.items():
            known_item = evaluate(method, corpus, store, known, return_ndcg=True)
            per_query[name] = known_item.pop("_ndcg_values")
            results[name] = {
                "known_item": known_item,
                "ambiguous": evaluate(method, corpus, store, ambiguous),
                "unanswerable": evaluate_unanswerable(method, corpus, store, unanswerable),
            }
        shipped = "shipped (fts5 index)"
        results["_deltas"] = {
            other: dict(zip(("mean", "low", "high"),
                            paired_delta(per_query[shipped], per_query[other])))
            for other in methods if other != shipped and shipped in per_query
        }
        results["_calibration"] = calibration(corpus, store, known, unanswerable)
        # The file the agent is editing, given as words and given as a path. The
        # relevant set is every page citing the file, so the second row is close
        # to the ceiling by construction; the first row is what today costs.
        touch_per_query = {name: [ndcg_at(method(q["q"], corpus, store), set(q["relevant"]))
                                  for q in touching]
                           for name, method in TOUCHING_METHODS.items()}
        results["_touching"] = {
            "n": len(touching),
            "methods": {name: evaluate(method, corpus, store, touching)
                        for name, method in TOUCHING_METHODS.items()},
            "delta": dict(zip(("mean", "low", "high"),
                              paired_delta(touch_per_query["--touching path"],
                                           touch_per_query["path as text query"])))
            if touching else {},
        }
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--by-type", action="store_true")
    args = ap.parse_args(argv)

    data = load_corpus()
    corpus = data["pages"]
    known = data["known_item"]
    ambiguous = data["ambiguous"]
    unanswerable = data["unanswerable"]
    results = compute()

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    print(f"corpus: {len(corpus)} pages | known-item: {len(known)} queries | "
          f"ambiguous: {len(ambiguous)} | unanswerable: {len(unanswerable)}\n")
    header = f"{'method':24} {'nDCG@10':>8} {'95% CI':>16} {'MRR':>6} {'R@1':>6} {'R@3':>6}"
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        if name.startswith("_"):
            continue
        k = r["known_item"]
        ci = f"[{k['ci'][0]:.3f},{k['ci'][1]:.3f}]"
        print(f"{name:24} {k['ndcg@10']:>8.3f} {ci:>16} {k['mrr@10']:>6.3f} "
              f"{k['recall@1']:>6.3f} {k['recall@3']:>6.3f}")

    print("\nshipped ranker vs each alternative, paired bootstrap over the same queries")
    for name, d in results["_deltas"].items():
        verdict = "significant" if (d["low"] > 0 or d["high"] < 0) else "NOT significant"
        print(f"  vs {name:24} {d['mean']:+.3f}  [{d['low']:+.3f},{d['high']:+.3f}]  {verdict}")

    print("\nambiguous queries (several pages relevant, best one should be first)")
    for name, r in results.items():
        if not name.startswith("_"):
            print(f"  {name:24} nDCG@10 {r['ambiguous']['ndcg@10']:.3f}")

    print("\nunanswerable queries (lower is better: share that got a hit anyway)")
    for name, r in results.items():
        if not name.startswith("_"):
            print(f"  {name:24} {r['unanswerable']['answered_anyway']:.0%}")

    cal = results["_calibration"]
    print("\nwhy that number cannot be fixed with a threshold — median of the top hit")
    print(f"  score     answerable {cal['score']['answerable_median']:.2f}   "
          f"unanswerable {cal['score']['unanswerable_median']:.2f}")
    print(f"  coverage  answerable {cal['coverage']['answerable_median']:.2f}   "
          f"unanswerable {cal['coverage']['unanswerable_median']:.2f}")

    touch = results["_touching"]
    if touch["n"]:
        print(f"\ntouching queries ({touch['n']}): the agent knows the file, not the words")
        for name, r in touch["methods"].items():
            k = r["known_item"] if "known_item" in r else r
            print(f"  {name:24} nDCG@10 {k['ndcg@10']:.3f}  "
                  f"[{k['ci'][0]:.3f},{k['ci'][1]:.3f}]  R@1 {k['recall@1']:.3f}")
        d = touch["delta"]
        verdict = "significant" if (d["low"] > 0 or d["high"] < 0) else "NOT significant"
        print(f"  --touching vs text, paired  {d['mean']:+.3f}  "
              f"[{d['low']:+.3f},{d['high']:+.3f}]  {verdict}")

    if args.by_type:
        scored = {n: r for n, r in results.items() if not n.startswith("_")}
        types = sorted({t for r in scored.values() for t in r["known_item"]["by_type"]})
        print("\nnDCG@10 by query type")
        print(f"  {'method':24}" + "".join(f"{t:>14}" for t in types))
        for name, r in scored.items():
            row = "".join(f"{r['known_item']['by_type'].get(t, 0):>14.3f}" for t in types)
            print(f"  {name:24}{row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
