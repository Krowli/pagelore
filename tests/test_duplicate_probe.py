"""`evals/duplicate_probe.py` on small, hand-built inputs — a correctness check
on the pure functions the probe's numbers depend on, not a probe run.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "evals"))

import duplicate_probe as dp  # noqa: E402


def test_jaccard_of_identical_sets_is_one():
    a = {"terminal", "pty", "reap"}
    assert dp.jaccard(a, set(a)) == 1.0


def test_jaccard_of_disjoint_sets_is_zero():
    assert dp.jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_of_two_empty_sets_is_zero_not_a_division_error():
    assert dp.jaccard(set(), set()) == 0.0


def test_jaccard_is_intersection_over_union():
    a = {"a", "b", "c"}
    b = {"b", "c", "d"}
    assert dp.jaccard(a, b) == pytest.approx(2 / 4)


def test_cosine_of_identical_vectors_is_one():
    v = {"a": 2.0, "b": 3.0}
    assert dp.cosine(v, dict(v)) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero():
    assert dp.cosine({"a": 1.0}, {"b": 1.0}) == 0.0


def test_cosine_of_an_empty_vector_is_zero():
    assert dp.cosine({}, {"a": 1.0}) == 0.0


def test_corpus_idf_gives_a_rarer_term_a_higher_weight():
    from collections import Counter

    doc_tf = [Counter({"common": 1, "rare": 1}),
              Counter({"common": 1}),
              Counter({"common": 1})]
    idf = dp.corpus_idf(doc_tf)
    assert idf["rare"] > idf["common"]


def test_tfidf_vector_scales_term_frequency_by_idf():
    from collections import Counter

    idf = {"a": 2.0, "b": 0.5}
    vec = dp.tfidf_vector(Counter({"a": 3, "b": 1}), idf)
    assert vec == {"a": 6.0, "b": 0.5}


def test_positive_pairs_reads_the_supersedes_field_as_a_bare_slug():
    pages = [
        {"slug": "new-decision", "supersedes": "old-decision"},
        {"slug": "old-decision"},
        {"slug": "unrelated"},
    ]
    pairs = dp.positive_pairs(pages)
    assert pairs == {frozenset((0, 1))}


def test_positive_pairs_also_accepts_a_list_shape():
    pages = [
        {"slug": "new-decision", "supersedes": ["old-a", "old-b"]},
        {"slug": "old-a"},
        {"slug": "old-b"},
    ]
    pairs = dp.positive_pairs(pages)
    assert pairs == {frozenset((0, 1)), frozenset((0, 2))}


def test_positive_pairs_ignores_a_supersedes_target_missing_from_the_corpus():
    pages = [{"slug": "new-decision", "supersedes": "never-written"}]
    assert dp.positive_pairs(pages) == set()


def test_threshold_for_fpr_admits_at_most_one_percent_of_negatives():
    # 100 negatives, scores 0.00..0.99: the 1% budget allows exactly one of them
    # at or above the threshold, so the threshold is the single highest score.
    neg = [i / 100 for i in range(100)]
    threshold = dp.threshold_for_fpr(neg, max_fpr=0.01)
    admitted = sum(1 for s in neg if s >= threshold)
    assert admitted <= 1
    assert threshold == pytest.approx(0.99)


def test_threshold_for_fpr_keeps_a_whole_tie_together():
    # Three negatives tied at the top: admitting any of them admits all three,
    # which is over a 1-in-100 budget, so the threshold must exclude the tie.
    neg = [0.9, 0.9, 0.9] + [i / 100 for i in range(97)]
    threshold = dp.threshold_for_fpr(neg, max_fpr=0.01)
    assert threshold > 0.9


def test_threshold_for_fpr_with_no_negatives_at_all():
    assert dp.threshold_for_fpr([], max_fpr=0.01) == 0.0


def test_page_tokens_combines_title_and_body():
    page = {"title": "PTY reap", "body": "waits on the child"}
    tokens = dp.page_tokens(page)
    assert "pty" in tokens
    assert "child" in tokens


def test_partner_map_is_symmetric_both_directions():
    pages = [{"slug": "a", "supersedes": "b"}, {"slug": "b"}, {"slug": "c"}]
    assert dp.partner_map(pages) == {0: 1, 1: 0}


def test_partner_map_ignores_a_target_missing_from_the_corpus():
    pages = [{"slug": "a", "supersedes": "nowhere"}]
    assert dp.partner_map(pages) == {}


def test_threshold_for_rate_budget_scales_with_total_not_with_len_of_scores():
    # Only 2 candidate scores, but the budget is over 100 attempts: 5% of 100
    # is 5, well above the 2 given, so both are admitted and the threshold is
    # their minimum — the per-pair threshold_for_fpr (total == len(scores))
    # could never produce this, since there `total` and `len(scores)` are the
    # same number by construction.
    threshold = dp.threshold_for_rate([0.5, 0.6], total=100, max_rate=0.05)
    assert threshold == 0.5


def test_threshold_for_rate_with_no_scores_at_all():
    assert dp.threshold_for_rate([], total=90, max_rate=0.01) == 0.0


def test_threshold_for_rate_with_zero_total():
    assert dp.threshold_for_rate([0.5], total=0, max_rate=0.01) == 0.0


def test_best_matches_picks_the_highest_scoring_other_index():
    # A tiny 4x4 score "matrix" as a dict, standing in for jaccard/cosine.
    scores = {
        (0, 1): 0.9, (0, 2): 0.1, (0, 3): 0.05,
        (1, 0): 0.9, (1, 2): 0.2, (1, 3): 0.05,
        (2, 0): 0.1, (2, 1): 0.2, (2, 3): 0.3,
        (3, 0): 0.05, (3, 1): 0.05, (3, 2): 0.3,
    }
    best_score, best_idx = dp.best_matches(4, lambda i, j: scores[(i, j)])
    assert best_idx == [1, 0, 3, 2]
    assert best_score == pytest.approx([0.9, 0.9, 0.3, 0.3])


def test_evaluate_per_write_counts_true_and_false_warnings_separately():
    # Pages 0 and 1 supersede each other and are each other's best match — a
    # correct pair on both sides (2 of the 2 writes with a correct answer).
    # Pages 2 and 3 have no partner at all, so their best match (each other,
    # at a lower score) can only ever be a false warning if it triggers.
    pages = [{"slug": "a", "supersedes": "b"}, {"slug": "b"},
             {"slug": "c"}, {"slug": "d"}]
    scores = {
        (0, 1): 0.9, (0, 2): 0.1, (0, 3): 0.05,
        (1, 0): 0.9, (1, 2): 0.2, (1, 3): 0.05,
        (2, 0): 0.1, (2, 1): 0.2, (2, 3): 0.3,
        (3, 0): 0.05, (3, 1): 0.05, (3, 2): 0.3,
    }
    result = dp.evaluate_per_write("test", pages, lambda i, j: scores[(i, j)])
    # The threshold must clear both false candidates (score 0.3 each) to hold
    # 0 false warnings out of 4 writes (1% of 4 rounds down to 0 admitted), so
    # it lands just above 0.3 — still comfortably below the true pair's 0.9.
    assert result["threshold"] > 0.3
    assert result["false_count"] == 0
    assert result["true_count"] == 2
    assert result["partner_count"] == 2
    assert result["recall"] == pytest.approx(1.0)
    assert result["fpr"] == pytest.approx(0.0)


def test_evaluate_per_write_recall_denominator_is_writes_not_pairs():
    """A page with no partner can never be a true warning, but it still counts
    toward `n_writes`/the false-warning denominator — recall's denominator is
    only the writes that HAVE a correct answer to reach."""
    pages = [{"slug": "a", "supersedes": "b"}, {"slug": "b"}, {"slug": "c"}]
    scores = {(0, 1): 0.9, (0, 2): 0.1, (1, 0): 0.9, (1, 2): 0.1,
              (2, 0): 0.1, (2, 1): 0.1}
    result = dp.evaluate_per_write("test", pages, lambda i, j: scores[(i, j)])
    assert result["partner_count"] == 2
    assert result["n_writes"] == 3


def test_a_partner_page_whose_best_match_is_a_third_page_counts_as_false(monkeypatch):
    """Having a supersedes partner is not enough to be eligible for recall: the
    best match has to actually BE that partner. Page 0 (`a`) supersedes `b`,
    but its highest-scoring match is `c`, a third, unrelated page — so even
    though `a` HAS a correct answer to reach, its high score must only ever be
    able to trigger a false warning, never a true one.
    """
    pages = [{"slug": "a", "supersedes": "b"}, {"slug": "b"}, {"slug": "c"}]
    scores = {
        (0, 1): 0.2, (0, 2): 0.9,   # a's best match is c (0.9), not b (0.2)
        (1, 0): 0.2, (1, 2): 0.05,  # b's best match correctly is a
        (2, 0): 0.3, (2, 1): 0.05,  # c has no partner; its best match is a
    }
    score_fn = lambda i, j: scores[(i, j)]  # noqa: E731

    _, best_idx = dp.best_matches(3, score_fn)
    assert best_idx[0] == 2  # a's best match is c, not its actual partner b

    # A permissive false-warning budget (module MAX_FPR is tuned for the real
    # 90-page corpus, not a 3-page fixture) so the threshold admits a's score
    # instead of rising above everything, the way it would at MAX_FPR's usual
    # 1%-of-90 budget.
    monkeypatch.setattr(dp, "MAX_FPR", 0.5)
    result = dp.evaluate_per_write("test", pages, score_fn)

    assert result["threshold"] == pytest.approx(0.9)
    assert result["false_count"] == 1  # a's 0.9 counted as a false warning...
    assert result["true_count"] == 0  # ...never as a true one
    assert result["recall"] == 0.0
