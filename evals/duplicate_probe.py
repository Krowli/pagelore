#!/usr/bin/env python3
"""Would a "looks like an existing page" warning on `lore write` catch real
duplicates without crying wolf on unrelated pages?

    python3 evals/duplicate_probe.py

The corpus (`evals/corpus.json`, 90 pages) has no labelled duplicates, so this
uses the one signal it does carry: 11 pages that `supersedes` another page are
pairs about the *same* topic, closer than any other pair in the corpus is
expected to be. Every other unordered pair (4005 total, so 3994 negatives) is
treated as a negative — an approximation, since the corpus was written to cover
distinct topics, not guaranteed distinct, but the best available substitute for
labelled duplicates.

Two measures over `pagelore.search.tokenize(title + " " + body)`:

  jaccard        |A ∩ B| / |A ∪ B| over each page's token set
  tfidf_cosine    cosine similarity of tf·idf vectors, idf computed via
                  `pagelore.search._idf` (the same Lucene-IDF formula the
                  shipped ranker uses) over document frequency counted across
                  this corpus

Two units, because they answer different questions and the first one measured
the wrong thing:

**Per pair** — of the 4005 unordered pairs, is a given pair's score at or above
the threshold. This is what a first pass at this probe reported, and it is the
wrong unit for a false-positive *budget*: the write path does not compare one
pair, it compares one new page against every other page in the store and warns
if the SINGLE BEST match clears the bar. At 90 pages that is 90 chances per
write for some unrelated page to score high by accident, not one.

**Per write** — for each of the 90 pages, treated in turn as the page being
newly created, against all 89 others: the best-scoring other page, and whether
that best match is (a) at or above the threshold (a warning fires) and (b), if
so, whether it is that page's actual `supersedes` partner (a true warning) or
not (a false warning). This is the unit the feature actually operates in, and
it is the one the decision is made on.

For recall's denominator: 11 supersedes pairs, both directions counted
separately (page A written with B as the best match, and B written with A as
the best match, are two different writes) — 22 writes that have a correct
answer to reach.

Decision rule, fixed before these numbers existed: if the better of the two
measures reaches recall >= 0.5 at <= 1% false warnings, PER WRITE, build the
warning with that measure and threshold. Otherwise, don't — a warning firing
on fewer than half the real duplicates, spent for one false alarm in a hundred
writes, is not worth an agent's attention.
"""
from __future__ import annotations

import itertools
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

import run as harness  # noqa: E402

from pagelore import search as memory_search  # noqa: E402

# The decision rule this probe exists to answer, fixed in advance — not tuned
# to whatever these numbers turn out to be.
MAX_FPR = 0.01
RECALL_FLOOR = 0.5


def page_tokens(page: dict) -> list[str]:
    """The tokens a page contributes to either measure: title and body as one
    bag of words, exactly what the brief for this probe specifies — not the
    title/body split `search.build_index` uses for BM25F, which weights and
    scores the two fields separately rather than measuring one page against
    another."""
    return memory_search.tokenize(f"{page['title']} {page['body']}")


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def corpus_idf(doc_tf: list[Counter]) -> dict[str, float]:
    """IDF per term, document frequency counted over the whole corpus. Reuses
    `search._idf` — the same Lucene-IDF formula the shipped ranker scores
    with — rather than a second formula that could quietly disagree with it."""
    df: Counter = Counter()
    for tf in doc_tf:
        df.update(set(tf))
    n_docs = len(doc_tf)
    return {term: memory_search._idf(count, n_docs) for term, count in df.items()}


def tfidf_vector(tf: Counter, idf: dict[str, float]) -> dict[str, float]:
    return {term: count * idf[term] for term, count in tf.items()}


def cosine(u: dict[str, float], v: dict[str, float]) -> float:
    if not u or not v:
        return 0.0
    common = u.keys() & v.keys()
    dot = sum(u[t] * v[t] for t in common)
    if not dot:
        return 0.0
    norm_u = sum(x * x for x in u.values()) ** 0.5
    norm_v = sum(x * x for x in v.values()) ** 0.5
    return dot / (norm_u * norm_v) if norm_u and norm_v else 0.0


def _supersedes_targets(page: dict) -> list[str]:
    """`supersedes` in this corpus is a bare slug string on the 11 pages that
    have one — write.py's own `--supersedes` is repeatable and stores a list,
    so both shapes are accepted here rather than assuming the corpus's."""
    value = page.get("supersedes")
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def positive_pairs(pages: list[dict]) -> set[frozenset[int]]:
    """Index pairs, by position in `pages`, that stand in a supersedes relation
    either way — the (page, superseded page) pairs this probe treats as the
    only known duplicates, for the per-pair unit."""
    slug_index = {p["slug"]: i for i, p in enumerate(pages)}
    pairs: set[frozenset[int]] = set()
    for i, page in enumerate(pages):
        for target in _supersedes_targets(page):
            j = slug_index.get(target)
            if j is not None:
                pairs.add(frozenset((i, j)))
    return pairs


def partner_map(pages: list[dict]) -> dict[int, int]:
    """Index -> the index of its supersedes partner, both directions.

    Symmetric and total: if A supersedes B, both `partner[A] = B` and
    `partner[B] = A` are set. This is the per-write unit's ground truth — a
    page not in this map has no correct answer to reach, ever, regardless of
    threshold.
    """
    slug_index = {p["slug"]: i for i, p in enumerate(pages)}
    out: dict[int, int] = {}
    for i, page in enumerate(pages):
        for target in _supersedes_targets(page):
            j = slug_index.get(target)
            if j is not None:
                out[i] = j
                out[j] = i
    return out


def threshold_for_rate(scores: list[float], total: int, max_rate: float) -> float:
    """The smallest threshold such that at most `max_rate` of `total` attempts
    score at or above it, where `scores` holds only the attempts that would
    count against the budget if they triggered (every other attempt among
    `total` never contributes a false hit at any threshold, so it is left out
    rather than padding `scores` with zeros that would never matter).

    Walking distinct values, not `sorted[limit - 1]`, so a tie straddling the
    limit is never split: every attempt at a given score either counts or none
    of them do, because the write path can only compare `>= threshold`, not
    single out individual candidates sharing one score.
    """
    if total == 0:
        return 0.0
    limit = int(total * max_rate)
    if not scores:
        return 0.0
    if limit >= len(scores):
        return min(scores)
    counts = Counter(scores)
    cumulative = 0
    best: float | None = None
    for value in sorted(counts, reverse=True):
        cumulative += counts[value]
        if cumulative <= limit:
            best = value
        else:
            break
    if best is not None:
        return best
    # Even the single highest-scoring attempt (or a tied group of them) already
    # exceeds the budget on its own: no achievable threshold admits it, so the
    # smallest safe threshold is just above the top score.
    top = max(scores)
    return top + (abs(top) * 1e-9 or 1e-9)


def threshold_for_fpr(neg_scores: list[float], max_fpr: float = MAX_FPR) -> float:
    """Per-pair threshold: every negative pair could independently trigger a
    false positive, so the budget is over exactly the negatives given."""
    return threshold_for_rate(neg_scores, len(neg_scores), max_fpr)


def evaluate_per_pair(name: str, pos: list[float], neg: list[float]) -> dict:
    threshold = threshold_for_fpr(neg)
    recall = sum(1 for s in pos if s >= threshold) / len(pos) if pos else 0.0
    fpr = sum(1 for s in neg if s >= threshold) / len(neg) if neg else 0.0
    return {
        "name": name, "threshold": threshold, "recall": recall, "fpr": fpr,
        "pos_min": min(pos), "pos_median": statistics.median(pos), "pos_max": max(pos),
        "neg_min": min(neg), "neg_median": statistics.median(neg), "neg_max": max(neg),
    }


def _print_per_pair(r: dict) -> None:
    print(r["name"])
    print(f"  threshold (smallest value keeping negatives' FP rate <= {MAX_FPR:.0%}): "
          f"{r['threshold']:.4f}")
    print(f"  recall on the 11 positives at that threshold: {r['recall']:.3f}  "
          f"(measured FP rate {r['fpr']:.3%})")
    print(f"  positives  min={r['pos_min']:.4f}  median={r['pos_median']:.4f}  "
          f"max={r['pos_max']:.4f}")
    print(f"  negatives  min={r['neg_min']:.4f}  median={r['neg_median']:.4f}  "
          f"max={r['neg_max']:.4f}\n")


def best_matches(n: int, score_fn) -> tuple[list[float], list[int]]:
    """For each of the `n` pages, the highest-scoring other page and its score
    — what `write.find_similar` actually computes, one row of the score matrix
    at a time rather than one pair."""
    best_score = [0.0] * n
    best_idx = [-1] * n
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            score = score_fn(i, j)
            if score > best_score[i]:
                best_score[i] = score
                best_idx[i] = j
    return best_score, best_idx


def evaluate_per_write(name: str, pages: list[dict], score_fn) -> dict:
    n = len(pages)
    partner = partner_map(pages)
    best_score, best_idx = best_matches(n, score_fn)
    correct = [i in partner and best_idx[i] == partner[i] for i in range(n)]

    # Every page whose best match is not its actual partner (including every
    # page with no partner at all — its best match is never correct, by
    # definition) is a chance for a false warning if it scores high enough.
    false_scores = [best_score[i] for i in range(n) if not correct[i]]
    # Only a page with a partner, whose best match already IS that partner,
    # can ever become a true warning — threshold only decides whether it does.
    true_scores = [best_score[i] for i in range(n) if correct[i]]

    threshold = threshold_for_rate(false_scores, n, MAX_FPR)
    false_count = sum(1 for s in false_scores if s >= threshold)
    true_count = sum(1 for s in true_scores if s >= threshold)
    partner_count = len(partner)  # 22: both directions of the 11 pairs

    return {
        "name": name, "threshold": threshold,
        "recall": (true_count / partner_count) if partner_count else 0.0,
        "fpr": false_count / n,
        "n_writes": n, "partner_count": partner_count,
        "false_count": false_count, "true_count": true_count,
        "correct_min": min(true_scores) if true_scores else None,
        "correct_median": statistics.median(true_scores) if true_scores else None,
        "correct_max": max(true_scores) if true_scores else None,
        "wrong_min": min(false_scores) if false_scores else None,
        "wrong_median": statistics.median(false_scores) if false_scores else None,
        "wrong_max": max(false_scores) if false_scores else None,
    }


def _print_per_write(r: dict) -> None:
    print(r["name"])
    print(f"  threshold (smallest value keeping false warnings <= {MAX_FPR:.0%} of "
          f"{r['n_writes']} writes): {r['threshold']:.4f}")
    print(f"  {r['true_count']} true warning(s) / {r['partner_count']} writes with a "
          f"correct answer -> recall {r['recall']:.3f}   "
          f"{r['false_count']} false warning(s) / {r['n_writes']} writes -> "
          f"FP rate {r['fpr']:.3%}")
    if r["correct_max"] is not None:
        print(f"  best-match score when correct  min={r['correct_min']:.4f}  "
              f"median={r['correct_median']:.4f}  max={r['correct_max']:.4f}")
    if r["wrong_max"] is not None:
        print(f"  best-match score when wrong    min={r['wrong_min']:.4f}  "
              f"median={r['wrong_median']:.4f}  max={r['wrong_max']:.4f}\n")


def _verdict(results: list[dict]) -> tuple[dict, bool]:
    best = max(results, key=lambda r: r["recall"])
    return best, best["recall"] >= RECALL_FLOOR


def main() -> int:
    data = harness.load_corpus()
    pages = data["pages"]
    n = len(pages)
    total_pairs = n * (n - 1) // 2
    positives = positive_pairs(pages)

    doc_tf = [Counter(page_tokens(p)) for p in pages]
    doc_sets = [set(tf) for tf in doc_tf]
    idf = corpus_idf(doc_tf)
    doc_vecs = [tfidf_vector(tf, idf) for tf in doc_tf]

    jaccard_score = lambda i, j: jaccard(doc_sets[i], doc_sets[j])  # noqa: E731
    cosine_score = lambda i, j: cosine(doc_vecs[i], doc_vecs[j])  # noqa: E731

    print(f"corpus: {n} pages, {total_pairs} unordered pairs, "
          f"{len(positives)} positive (supersedes) pairs, "
          f"{total_pairs - len(positives)} negative\n")

    print("=== per pair (informational — see the module docstring for why this "
          "is the wrong unit for the decision) ===\n")
    jaccard_pos: list[float] = []
    jaccard_neg: list[float] = []
    cosine_pos: list[float] = []
    cosine_neg: list[float] = []
    for i, j in itertools.combinations(range(n), 2):
        is_positive = frozenset((i, j)) in positives
        j_score = jaccard_score(i, j)
        c_score = cosine_score(i, j)
        (jaccard_pos if is_positive else jaccard_neg).append(j_score)
        (cosine_pos if is_positive else cosine_neg).append(c_score)

    per_pair = [
        evaluate_per_pair("jaccard", jaccard_pos, jaccard_neg),
        evaluate_per_pair("tfidf_cosine", cosine_pos, cosine_neg),
    ]
    for r in per_pair:
        _print_per_pair(r)

    per_pair_best, per_pair_build = _verdict(per_pair)
    if per_pair_build:
        print(f"VERDICT (per pair, informational, NOT deciding): build "
              f"({per_pair_best['name']} >= {per_pair_best['threshold']:.4f})\n")
    else:
        print(f"VERDICT (per pair, informational, NOT deciding): do not build "
              f"(best measure {per_pair_best['name']} reaches only "
              f"{per_pair_best['recall']:.3f} recall at <= {MAX_FPR:.0%} FP)\n")

    print("=== per write (deciding — one write compares against every other "
          "page and warns on its single best match) ===\n")
    per_write = [
        evaluate_per_write("jaccard", pages, jaccard_score),
        evaluate_per_write("tfidf_cosine", pages, cosine_score),
    ]
    for r in per_write:
        _print_per_write(r)

    per_write_best, per_write_build = _verdict(per_write)
    if per_write_build:
        print(f"VERDICT (per write, DECIDING): build "
              f"({per_write_best['name']} >= {per_write_best['threshold']:.4f})")
    else:
        print(f"VERDICT (per write, DECIDING): do not build (best measure "
              f"{per_write_best['name']} reaches only {per_write_best['recall']:.3f} "
              f"recall at <= {MAX_FPR:.0%} false warnings per write, "
              f"below the {RECALL_FLOOR} recall floor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
