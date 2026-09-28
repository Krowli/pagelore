"""`evals/agent_eval.py` without a model: the stream parser, the metrics, the
projects both arms are given, the summary arithmetic, and the task file.

The sessions themselves cost money and run minutes; everything that decides how a
session is *scored* is pure and checked here, so a mis-scored run is a failing test
rather than a number nobody questions.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "evals"))

import agent_eval as ae  # noqa: E402


def stream(*events) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def tool_use(tid, name, **inp):
    return {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "thinking aloud"},
        {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def tool_result(tid, error=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": "…"}]}}


INIT = {"type": "system", "subtype": "init", "model": "claude-test-1",
        "claude_code_version": "9.9.9", "session_id": "s1",
        "mcp_servers": [{"name": "pagelore", "status": "connected"}],
        "skills": ["a", "b", "c"], "plugins": [{"name": "p"}], "agents": ["x", "y"],
        "memory_paths": {"project": "/p/CLAUDE.md"}}
RESULT = {"type": "result", "subtype": "success", "result": "The store has no page on it.",
          "num_turns": 7, "duration_ms": 12000, "total_cost_usd": 0.12, "is_error": False,
          "permission_denials": [{"tool_name": "Bash"}]}


@pytest.fixture()
def parsed():
    text = stream(
        INIT,
        tool_use("t1", "Read", file_path="/p/.memory/render-scrollback-cap.md"),
        tool_result("t1"),
        tool_use("t2", "Bash", command='lore search "scrollback cap"'),
        tool_result("t2"),
        tool_use("t3", "Edit", file_path="/p/src/terminal/scrollback/journal.ts",
                 old_string="10_000", new_string="50_000"),
        tool_result("t3"),
        tool_use("t4", "mcp__pagelore__memory_search", query="journal", touching=["x.ts"]),
        tool_result("t4", error=True),
        RESULT,
    )
    return ae.parse_stream(text + "not json at all\n")


def test_parse_stream_reads_init_tools_and_result(parsed):
    env = parsed["env"]
    assert env["model"] == "claude-test-1"
    assert env["claude_code_version"] == "9.9.9"
    assert env["mcp_servers"] == [{"name": "pagelore", "status": "connected"}]
    assert (env["n_skills"], env["n_plugins"], env["n_agents"]) == (3, 1, 2)
    assert [t["name"] for t in parsed["tools"]] == [
        "Read", "Bash", "Edit", "mcp__pagelore__memory_search"]
    assert [t["error"] for t in parsed["tools"]] == [False, False, False, True]
    assert parsed["tools"][1]["input"]["command"] == 'lore search "scrollback cap"'
    r = parsed["result"]
    assert r["answer"] == "The store has no page on it."
    assert (r["num_turns"], r["duration_ms"], r["total_cost_usd"], r["is_error"]) == (
        7, 12000, 0.12, False)
    assert r["permission_denials"] == [{"tool_name": "Bash"}]


def test_parse_stream_without_a_result_is_not_a_crash():
    got = ae.parse_stream(stream(INIT, tool_use("t1", "Read", file_path="a")))
    assert got["result"]["answer"] == ""
    assert got["result"]["is_error"] is None


LOG = [
    {"event": "search", "query": "a", "hits": 3, "top": "p1", "via": "cli"},
    {"event": "search", "query": "b", "hits": 3, "top": "p2", "via": "cli"},
    {"event": "search", "query": "c", "hits": 3, "top": "p1", "via": "cli"},
    {"event": "search", "query": "", "hits": 1, "top": "p1", "via": "cli",
     "touching": ["src/x.ts"], "touched": 1},
    {"event": "search", "query": "d", "hits": 0, "top": None, "via": "cli"},
    {"event": "search", "query": "e", "hits": 0, "top": None, "via": "cli"},
    {"event": "reject", "code": "no_sources", "slug": "x"},
    {"event": "write", "slug": "new-page", "kind": "bug", "mode": "create"},
]


def test_metrics_count_repeats_touching_and_writes(parsed):
    task = {"id": "C", "kind": "edit", "answer_any": ["26 mb"]}
    m = ae.metrics(task, parsed["tools"], parsed["result"]["answer"], LOG)
    assert m["searched"] is True
    assert m["n_searches"] == 6
    # p1 again twice; a search with no hits has no top and repeats nothing
    assert m["repeats"] == 2
    assert m["used_touching"] is True
    assert m["wrote_page"] is True
    assert (m["n_writes"], m["n_rejects"]) == (1, 1)
    assert m["grep_memory"] is False
    assert m["read_memory_file"] is True
    assert m["edited"] is True
    # the Bash search (index 1) came before the Edit (index 2)
    assert m["searched_before_edit"] is True
    assert m["correct"] is False


def test_searched_before_edit_is_false_when_the_search_came_after():
    tools = [{"name": "Write", "input": {"file_path": "/p/src/a.ts"}, "error": False},
             {"name": "Bash", "input": {"command": "lore search x"}, "error": False}]
    m = ae.metrics({"id": "C", "kind": "edit"}, tools, "", LOG[:1])
    assert m["searched_before_edit"] is False


def test_searched_before_edit_is_false_when_the_log_has_no_search():
    """A search call the harness refused never reached the store; it is not a search."""
    tools = [{"name": "Bash", "input": {"command": "cd x && lore search x"}, "error": True},
             {"name": "Edit", "input": {"file_path": "/p/src/a.ts"}, "error": False}]
    m = ae.metrics({"id": "C", "kind": "edit"}, tools, "", [])
    assert m["searched"] is False
    assert m["searched_before_edit"] is False


def test_a_refused_edit_is_not_the_first_edit():
    tools = [{"name": "Edit", "input": {"file_path": "/p/src/a.ts"}, "error": True},
             {"name": "Bash", "input": {"command": "lore search x"}, "error": False},
             {"name": "Edit", "input": {"file_path": "/p/src/a.ts"}, "error": False}]
    m = ae.metrics({"id": "C", "kind": "edit"}, tools, "", LOG[:1])
    assert m["searched_before_edit"] is True


def test_a_search_is_a_command_that_runs_lore():
    def search(command):
        return ae.is_search({"name": "Bash", "input": {"command": command}})
    assert search('echo "lore search x"') is False
    assert search("grep -n 'lore search' README.md") is False
    assert search("cd /p && lore search x") is True
    assert search("PAGELORE_X=1 lore search x | head") is True
    assert search("pagelore search x") is True
    assert search("lore show x") is False


def test_searched_before_edit_is_none_without_an_edit():
    tools = [{"name": "mcp__pagelore__memory_search", "input": {"query": "x"}, "error": False},
             # writing into the store by hand is not an edit of the task's code
             {"name": "Write", "input": {"file_path": "/p/.memory/x.md"}, "error": False}]
    m = ae.metrics({"id": "A", "kind": "why"}, tools, "", LOG[:1])
    assert m["edited"] is False
    assert m["searched_before_edit"] is None
    assert m["used_touching"] is False
    assert m["wrote_page"] is False


@pytest.mark.parametrize("tool, scans, reads", [
    ({"name": "Grep", "input": {"pattern": "cap", "path": ".memory"}}, True, False),
    ({"name": "Glob", "input": {"pattern": ".memory/**/*.md"}}, True, False),
    # chained after a search in one call, as a smoke session did
    ({"name": "Bash", "input": {"command": 'lore search "x"; grep -rn sixel .memory src'}},
     True, False),
    ({"name": "Bash", "input": {"command": "find .memory -name '*.md' | head"}}, True, False),
    # a `|` inside the quoted pattern does not end the command
    ({"name": "Bash", "input": {"command": 'lore search "a"; grep -rniE "sixel|inline image" '
                                           '.memory src | head'}}, True, False),
    ({"name": "Bash", "input": {"command": "lore write --slug x --body - <<'PMEOF'\n"
                                           "it's in .memory, don't grep\nPMEOF"}}, False, False),
    ({"name": "Bash", "input": {"command": "lore write --slug x --body - <<'PMEOF'\n"
                                           "grep the .memory dir\nPMEOF"}}, False, False),
    # opening a hit, as the MCP arm must: it has no `show`
    ({"name": "Bash", "input": {"command": "cat .memory/x.md 2>/dev/null || ls .memory"}},
     False, True),
    ({"name": "Read", "input": {"file_path": "/p/.memory/x.md"}}, False, True),
    ({"name": "Read", "input": {"file_path": "/p/src/a.ts"}}, False, False),
    ({"name": "Bash", "input": {"command": "lore search x --store .memory"}}, False, False),
    ({"name": "Grep", "input": {"pattern": "memory", "path": "src"}}, False, False),
    # no path is the project root, and the root holds the store (mcp B in the smoke run)
    ({"name": "Grep", "input": {"pattern": "(?i)sixel|iterm", "output_mode": "content"}},
     True, False),
    ({"name": "Grep", "input": {"pattern": "x", "path": "."}}, True, False),
    ({"name": "Grep", "input": {"pattern": "x", "path": "/p/project"}}, True, False),
    ({"name": "Grep", "input": {"pattern": "x", "path": "/p/project/src"}}, False, False),
    ({"name": "Grep", "input": {"pattern": "x", "type": "ts"}}, False, False),
    ({"name": "Grep", "input": {"pattern": "x", "glob": "*.ts"}}, False, False),
    ({"name": "Grep", "input": {"pattern": "x", "glob": "*.md"}}, True, False),
    ({"name": "Glob", "input": {"pattern": "**/*.md"}}, True, False),
    ({"name": "Glob", "input": {"pattern": "*.md"}}, False, False),
    ({"name": "Glob", "input": {"pattern": "src/**/*.ts"}}, False, False),
    ({"name": "Bash", "input": {"command": "cd .memory && grep -l scrollback *"}}, True, False),
    ({"name": "Bash", "input": {"command": "git grep -n cap -- .memory"}}, True, False),
    ({"name": "Bash", "input": {"command": "grep -rn scrollback ."}}, True, False),
    ({"name": "Bash", "input": {"command": "grep -rn scrollback"}}, True, False),
    ({"name": "Bash", "input": {"command": "grep -n scrollback src/a.ts"}}, False, False),
    ({"name": "Bash", "input": {"command": "rg scrollback"}}, False, False),
    ({"name": "Bash", "input": {"command": "rg --hidden scrollback"}}, True, False),
    ({"name": "Bash", "input": {"command": "find . -name '*.md'"}}, True, False),
    ({"name": "Bash", "input": {"command": "find src -name '*.ts'"}}, False, False),
    ({"name": "Bash", "input": {"command": "cd .memory && cat x.md"}}, False, True),
    # a pattern that mentions `.memory` is text, not a place searched
    ({"name": "Grep", "input": {"pattern": r"\.memory/", "path": "src"}}, False, False),
    ({"name": "Grep", "input": {"pattern": ".memory", "glob": "*.ts"}}, False, False),
    ({"name": "Grep", "input": {"pattern": "x", "glob": ".memory/*.md"}}, True, False),
    ({"name": "Bash", "input": {"command": "grep -rn '.memory' src"}}, False, False),
    ({"name": "Bash", "input": {"command": "git grep -n '.memory/' -- src"}}, False, False),
    ({"name": "Bash", "input": {"command": "rg '.memory' src"}}, False, False),
    # a find reaches the store only when no name filter excludes a page
    ({"name": "Bash", "input": {"command": "find . -name '*.ts'"}}, False, False),
    ({"name": "Bash", "input": {"command": "find . -type f"}}, True, False),
    ({"name": "Bash", "input": {"command": "find . -iname '*.MD'"}}, True, False),
    ({"name": "Bash", "input": {"command": "find . -path '*/.memory/*' -name '*.md'"}},
     True, False),
    ({"name": "Bash", "input": {"command": "find .memory -name '*.ts'"}}, False, False),
])
def test_grep_and_read_memory(tool, scans, reads):
    m = ae.metrics({"id": "A", "kind": "why"}, [{**tool, "error": False}], "", [],
                   root="/p/project")
    assert (m["grep_memory"], m["read_memory_file"]) == (scans, reads)


TASK = {t["id"]: t for t in ae.load_tasks()}


def correct(tid, answer):
    return ae.metrics(TASK[tid], [], answer, [])["correct"]


def test_answer_matching_is_case_insensitive_normalised_and_on_word_boundaries():
    task = {"id": "X", "kind": "why", "answer_any": ["26 mb", "oom", "16 s"]}
    assert ae.metrics(task, [], "about 26MB per pane", [])["correct"] is True
    assert ae.metrics(task, [], "about 26\u00a0MB per pane", [])["correct"] is True
    assert ae.metrics(task, [], "waits 16s", [])["correct"] is True
    # "oom" inside "room" is not the word; "126 mb" is not "26 mb"
    assert ae.metrics(task, [], "there is room, 126 MB", [])["correct"] is False
    assert ae.metrics(task, [], "", [])["correct"] is False


@pytest.mark.parametrize("tid, general", [
    ("A", "SQLite 3.35 added RETURNING and 3.37 added STRICT tables, which older system "
          "libraries lack, so bundling gives a known version."),
    ("A", "Debian bullseye ships SQLite 3.34 and RHEL 8 ships 3.26, both too old."),
    ("C", "A larger buffer uses more memory and could run out of memory with many panes."),
    ("D", "Failed turns are retried with exponential backoff and jitter by the transport, "
          "honouring Retry-After."),
    ("F", "Sync polls less often when a machine is idle to save battery and requests."),
])
def test_general_knowledge_does_not_score(tid, general):
    assert correct(tid, general) is False


@pytest.mark.parametrize("tid, answer", [
    ("A", "It is pinned to 3.45.x on every platform."),
    ("A", "The binary grows by about 1.4MB."),
    ("C", "The page says a full pane costs 26 MB."),
    ("D", "Only before the first response byte; after that the pane shows a Resume button."),
    ("F", "An idle machine polls only every 15 minutes because S3 LIST requests cost."),
    ("F", "It backs off to a 15-minute interval."),
])
def test_page_facts_score(tid, answer):
    assert correct(tid, answer) is True


def test_unanswerable_is_correct_only_when_it_says_the_memory_lacks_it():
    m = ae.metrics(TASK["B"], [], "The memory doesn\u2019t say; it is Not Recorded.", [])
    assert (m["abstained"], m["correct"]) == (True, True)
    assert correct("B", "I couldn't find any page on it.") is True
    assert correct("B", "Yes, sixel is supported via the image layer.") is False
    # a hedge word is not an abstention
    assert correct("B", "Support is unknown and unclear, but probably yes.") is False


@pytest.mark.parametrize("answer, current, mentions, endorses", [
    ("Only before the first response byte, via reqwest. The old loop that waited "
     "1s, 4s, 16s with \u00b125% jitter was dropped.", True, True, False),
    ("The orchestrator waits 1 s, 4 s and 16 s with \u00b125% jitter, then fails.",
     False, True, True),
    ("orchestrator/retry.ts retries: 1s \u2192 4s \u2192 16s.", False, True, True),
    ("Retries happen before the first response byte, at most 8 retries per run.",
     True, False, False),
    ("Something vague about retries.", False, False, False),
])
def test_superseded_endorsement_needs_the_old_decision_without_the_new(
        answer, current, mentions, endorses):
    m = ae.metrics(TASK["D"], [], answer, [])
    assert (m["correct"], m["mentions_obsolete"], m["endorses_obsolete"]) == (
        current, mentions, endorses)


def test_ungraded_fields_are_none():
    m = ae.metrics({"id": "E", "kind": "bugfix"}, [], "fixed", [])
    assert m["correct"] is None and m["abstained"] is None
    assert m["mentions_obsolete"] is None and m["endorses_obsolete"] is None


# --- summary -------------------------------------------------------------------

@pytest.mark.parametrize("k, n, lo, hi", [
    (5, 10, 0.2366, 0.7634),
    (0, 10, 0.0, 0.2775),
    (10, 10, 0.7225, 1.0),
    (1, 3, 0.0615, 0.7923),
])
def test_wilson(k, n, lo, hi):
    got = ae.wilson(k, n)
    assert got[0] == pytest.approx(lo, abs=1e-4)
    assert got[1] == pytest.approx(hi, abs=1e-4)


def test_wilson_of_nothing_is_none():
    assert ae.wilson(0, 0) is None


@pytest.mark.parametrize("ka, na, kb, nb, p", [
    (3, 4, 1, 4, 0.4857),            # Fisher's tea-tasting table
    (10, 10, 0, 10, 1.0825e-05),     # 2 / C(20, 10)
    (5, 10, 5, 10, 1.0),
    (1, 3, 1, 3, 1.0),
])
def test_fisher_exact(ka, na, kb, nb, p):
    assert ae.fisher_exact(ka, na, kb, nb) == pytest.approx(p, rel=1e-3)
    assert ae.fisher_exact(kb, nb, ka, na) == pytest.approx(p, rel=1e-3)


def test_fisher_of_nothing_is_none():
    assert ae.fisher_exact(0, 0, 1, 2) is None


def test_newcombe_matches_the_published_example():
    # Newcombe 1998, Stat Med 17:873, example (a): 56/70 vs 48/80, method 10
    lo, hi = ae.newcombe(48, 80, 56, 70)
    assert (lo, hi) == (pytest.approx(0.0524, abs=1e-4), pytest.approx(0.3339, abs=1e-4))
    lo, hi = ae.newcombe(56, 70, 48, 80)
    assert (lo, hi) == (pytest.approx(-0.3339, abs=1e-4), pytest.approx(-0.0524, abs=1e-4))
    assert ae.newcombe(0, 0, 1, 1) is None


@pytest.mark.parametrize("a, b, p", [
    ([1, 2, 3], [4, 5, 6], 0.0809),              # scipy asymptotic, continuity-corrected
    ([1, 2, 3, 4, 5], [6, 7, 8, 9, 10], 0.0122),
    ([1, 1, 2, 2], [2, 3, 3, 3], 0.0471),        # with ties: U=1, σ²=10.714
    ([2, 2, 2], [2, 2], 1.0),                    # all tied
])
def test_mann_whitney(a, b, p):
    assert ae.mann_whitney(a, b) == pytest.approx(p, abs=5e-4)


def test_mann_whitney_of_nothing_is_none():
    assert ae.mann_whitney([], [1]) is None


def session(arm, task, **m):
    base = {"type": "session", "arm": arm, "task": task, "searched": False, "n_searches": 0,
            "repeats": 0, "used_touching": False, "searched_before_edit": None,
            "wrote_page": False, "grep_memory": False, "correct": None, "num_turns": 4,
            "total_cost_usd": 0.1, "is_error": False, "timed_out": False}
    return {**base, **m}


def test_summarize_groups_rates_and_medians():
    rows = [session("include", "A", searched=True, n_searches=2, repeats=1, correct=True,
                    num_turns=3, total_cost_usd=0.1),
            session("include", "A", searched=True, n_searches=4, repeats=0, correct=False,
                    num_turns=5, total_cost_usd=0.3),
            session("include", "A", searched=False, correct=None, num_turns=7,
                    total_cost_usd=0.2, is_error=True),
            session("mcp", "A", searched=False, correct=False)]
    groups = {(g["model"], g["arm"], g["task"]): g for g in ae.summarize(rows)}
    g = groups[("?", "include", "A")]
    assert g["n"] == 3 and g["errors"] == 1
    assert (g["searched"]["k"], g["searched"]["n"]) == (2, 3)
    assert g["searched"]["lo"] == pytest.approx(ae.wilson(2, 3)[0])
    # None is "not applicable" and leaves the denominator
    assert (g["correct"]["k"], g["correct"]["n"]) == (1, 2)
    assert g["searched_before_edit"]["n"] == 0 and g["searched_before_edit"]["rate"] is None
    assert g["median_searches"] == 2
    assert g["mean_repeats"] == pytest.approx(1 / 3)
    assert g["median_turns"] == 5
    assert g["median_cost"] == pytest.approx(0.2)
    assert groups[("?", "mcp", "A")]["searched"]["k"] == 0
    assert g["values"]["n_searches"] == [2, 4, 0]


def test_summarize_groups_by_the_model_that_ran():
    rows = [session("include", "A", model="claude-opus-5-5"),
            session("include", "A", model="claude-sonnet-5"),
            session("include", "A", model=None, requested_model="claude-sonnet-5")]
    groups = {(g["model"], g["arm"], g["task"]): g["n"] for g in ae.summarize(rows)}
    assert groups == {("claude-opus-5-5", "include", "A"): 1,
                      ("claude-sonnet-5", "include", "A"): 2}


def test_compare_two_files_prints_the_difference(tmp_path, capsys):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    header = {"type": "header", "label": "x"}
    a.write_text("\n".join(json.dumps(r) for r in [
        header, session("include", "A", searched=False),
        session("include", "A", searched=True)]) + "\n", encoding="utf-8")
    b.write_text("\n".join(json.dumps(r) for r in [
        header, session("include", "A", searched=True),
        session("include", "A", searched=True)]) + "\n", encoding="utf-8")
    assert ae.main(["--summarize", str(a), str(b), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    diff = {(d["arm"], d["task"], d["metric"]): d for d in data["diff"]}
    d = diff[("include", "A", "searched")]
    assert (d["a"], d["b"]) == (0.5, 1.0)
    assert d["delta"] == pytest.approx(0.5)
    assert (d["lo"], d["hi"]) == pytest.approx(ae.newcombe(1, 2, 2, 2))
    assert d["p"] == pytest.approx(ae.fisher_exact(1, 2, 2, 2))
    assert d["significant"] is False
    n = diff[("include", "A", "n_searches")]
    assert n["kind"] == "median" and n["p"] == pytest.approx(1.0)
    assert ae.main(["--summarize", str(a), str(b)]) == 0
    text = capsys.readouterr().out
    assert "searched" in text and "+50pp" in text and "Fisher" in text


def test_compare_marks_a_significant_row(tmp_path, capsys):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("".join(json.dumps(session("mcp", "B", searched=False)) + "\n"
                         for _ in range(10)), encoding="utf-8")
    b.write_text("".join(json.dumps(session("mcp", "B", searched=True, n_searches=5)) + "\n"
                         for _ in range(10)), encoding="utf-8")
    assert ae.main(["--summarize", str(a), str(b)]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines()
                if " searched " in x and "mcp" in x)
    assert line.rstrip().endswith("*") and "+100pp" in line


# --- tasks ---------------------------------------------------------------------

def test_tasks_rest_on_real_corpus_pages_and_paths():
    corpus = json.loads((HERE.parent / "evals" / "corpus.json").read_text(encoding="utf-8"))
    pages = {p["slug"]: p for p in corpus["pages"]}
    cited = {s for p in corpus["pages"] for s in p.get("sources") or []}
    tasks = ae.load_tasks()
    assert [t["id"] for t in tasks] == ["A", "B", "C", "D", "E", "F"]
    for t in tasks:
        assert t["prompt"] and t["kind"] and t["correct_means"]
        assert set(t["pages"]) <= set(pages), t["id"]
        assert set(t["files"]) <= cited, t["id"]
        if "target" in t:
            assert t["target"] in t["files"]
            assert t["target"] in pages[t["pages"][0]]["sources"]
    by = {t["id"]: t for t in tasks}
    assert by["B"]["unanswerable"] in corpus["unanswerable"] and not by["B"]["pages"]
    assert by["B"]["abstain_any"]
    current, old = by["D"]["pages"]
    assert pages[current].get("supersedes") == old
    assert by["D"]["answer_any"] and by["D"]["obsolete_any"]
    assert by["A"]["answer_any"] and len(by["A"]["pages"]) == 1
    assert by["F"]["answer_any"] and len(by["F"]["pages"]) == 1


def test_every_graded_phrase_is_a_fact_of_its_page():
    """`correct` must not be earned from general knowledge, so every phrase is
    quoted from the page it grades — or declared `derived` — and `obsolete_any`
    from the superseded page, whose regexes must match that page too."""
    corpus = json.loads((HERE.parent / "evals" / "corpus.json").read_text(encoding="utf-8"))
    pages = {p["slug"]: ae.normalise(p["title"] + "\n" + p["body"]) for p in corpus["pages"]}
    for t in ae.load_tasks():
        derived = set(t.get("derived") or [])
        for phrase in set(t.get("answer_any") or []) - derived:
            if phrase in t["pages"]:
                continue
            assert ae.matches(pages[t["pages"][0]], [phrase]), (t["id"], phrase)
        for phrase in t.get("obsolete_any") or []:
            assert ae.matches(pages[t["pages"][1]], [phrase]), (t["id"], phrase)
            assert not ae.matches(pages[t["pages"][0]], [phrase]), (t["id"], phrase)


# --- projects ------------------------------------------------------------------

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the harness refuses to build sessions on Windows: the `lore` shim it puts on "
           "the agent's PATH is a POSIX shell script")


def dry_run(tmp_path, monkeypatch, capsys, *extra):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert ae.main(["--dry-run", "--arms", "include,mcp", "--tasks", "C", *extra]) == 0
    out = capsys.readouterr().out
    sessions = {}
    for line in out.splitlines():
        m = re.match(r"^(include|mcp) (\w) (\S+)$", line)
        if m:
            sessions[m.group(1)] = Path(m.group(3))
        if line.startswith("$ "):
            sessions[list(sessions)[-1] + ":cmd"] = shlex.split(line[2:])
    return out, sessions


def flag(cmd, name):
    return cmd[cmd.index(name) + 1]


@POSIX_ONLY
def test_dry_run_builds_the_include_project(tmp_path, monkeypatch, capsys):
    out, s = dry_run(tmp_path, monkeypatch, capsys)
    assert f"pagelore {ae.__version__}" in out
    project, cmd = s["include"], s["include:cmd"]
    line = (project / "CLAUDE.md").read_text(encoding="utf-8").strip()
    assert line.startswith("@") and Path(line[1:]).is_absolute()
    assert "lore search" in Path(line[1:]).read_text(encoding="utf-8")
    assert not (project / ".mcp.json").exists()
    assert (project / "src/terminal/scrollback/journal.ts").is_file()
    assert (project / ".memory" / "render-scrollback-cap.md").is_file()
    assert cmd[:3] == ["claude", "-p", ae.load_tasks()[2]["prompt"]]
    assert "--strict-mcp-config" in cmd
    assert json.loads(Path(flag(cmd, "--mcp-config")).read_text()) == {"mcpServers": {}}
    assert flag(cmd, "--setting-sources") == "project"
    assert flag(cmd, "--output-format") == "stream-json"
    assert "--no-session-persistence" in cmd and "--verbose" in cmd
    tools = cmd[cmd.index("--allowedTools") + 1:]
    assert tools == ["Bash(lore:*)", "Read", "Edit", "Write", "Grep", "Glob"]
    assert "--model" not in cmd


@POSIX_ONLY
def test_dry_run_builds_the_mcp_project_with_a_working_server(tmp_path, monkeypatch, capsys):
    _, s = dry_run(tmp_path, monkeypatch, capsys, "--models", "claude-x")
    project, cmd = s["mcp"], s["mcp:cmd"]
    assert not (project / "CLAUDE.md").exists() and not (project / "AGENTS.md").exists()
    config = project / ".mcp.json"
    assert Path(flag(cmd, "--mcp-config")) == config
    assert "--strict-mcp-config" in cmd
    assert flag(cmd, "--model") == "claude-x"
    tools = cmd[cmd.index("--allowedTools") + 1:]
    assert "mcp__pagelore__memory_search" in tools and "mcp__pagelore__memory_write" in tools
    server = json.loads(config.read_text())["mcpServers"]
    assert list(server) == ["pagelore"]
    entry = server["pagelore"]
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "memory_search", "arguments": {"query": "scrollback cap"}}},
    ]
    proc = subprocess.run([entry["command"], *entry["args"]], cwd=project,
                          input="".join(json.dumps(r) + "\n" for r in requests),
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env={**ae.child_env(tmp_path / "bin", tmp_path / "home"),
                               **entry["env"]})
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert replies[1]["result"]["content"][0]["text"].count("render-scrollback-cap") >= 1
    events = ae.log_events(project / ".memory")
    assert events[-1]["event"] == "search" and events[-1]["via"] == "mcp"


def test_child_env_strips_the_parent_session_and_pagelore_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("PAGELORE_NO_LOG", "1")
    env = ae.child_env(tmp_path / "bin", tmp_path / "home")
    assert not [k for k in env if k == "CLAUDECODE" or (k.startswith("CLAUDE_CODE_")
                and k != "CLAUDE_CODE_OAUTH_TOKEN")]
    assert "PAGELORE_NO_LOG" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "bin")
    assert env["PAGELORE_HOME"] == str(tmp_path / "home")


def test_tidy_auto_memory_removes_only_its_own_empty_directory(tmp_path, monkeypatch):
    # Path.home() reads HOME on POSIX and USERPROFILE on Windows
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    projects = tmp_path / ".claude" / "projects"
    empty = projects / "-T-pm-agent-eval-abc-include-A-0-project"
    used = projects / "-T-pm-agent-eval-abc-mcp-A-0-project"
    other = projects / "-Users-me-work"
    for d in (empty, used, other):
        (d / "memory").mkdir(parents=True)
    (used / "memory" / "note.md").write_text("x", encoding="utf-8")
    assert ae.tidy_auto_memory({"auto": str(empty / "memory") + "/"}) == 0
    assert not empty.exists()
    assert ae.tidy_auto_memory({"auto": str(used / "memory")}) == 1
    assert used.exists()
    assert ae.tidy_auto_memory({"auto": str(other / "memory")}) == 0
    assert other.exists()
    assert ae.tidy_auto_memory(None) == 0


def test_an_existing_results_file_is_not_merged_into_without_append(tmp_path, capsys):
    out = tmp_path / "r.jsonl"
    out.write_text('{"type": "header"}\n', encoding="utf-8")
    assert ae.main(["--out", str(out), "--tasks", "A", "--runs", "1"]) == 2
    assert "--append" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == '{"type": "header"}\n'


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")
def test_a_timeout_kills_the_whole_process_tree(tmp_path):
    import time
    pidfile = tmp_path / "pid"
    started = time.perf_counter()
    done = ae.run_session(tmp_path, ["sh", "-c", f"sleep 30 & echo $! > {pidfile}; wait"],
                          dict(os.environ), timeout=1)
    assert done["timed_out"] is True and done["exit_code"] is None
    assert time.perf_counter() - started < 15
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the grandchild outlived the timeout")


def test_summarize_rescores_stale_records_and_says_so(tmp_path, capsys):
    """A file written under older rules is summarized under the current ones:
    stored metrics are never trusted, and the difference is announced."""
    tools = [{"name": "Grep", "input": {"pattern": "(?i)sixel"}, "error": False}]
    log = [{"event": "search", "query": "sixel", "hits": 3, "top": "p1", "via": "mcp"}]
    stale = {**session("mcp", "B", searched=True, n_searches=1, grep_memory=False,
                       correct=True, abstained=True),
             "scoring_version": 1, "tools": tools, "log": log,
             "answer": "Support is unknown."}
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps({"type": "header"}) + "\n" + json.dumps(stale) + "\n",
                    encoding="utf-8")
    assert ae.main(["--summarize", str(path), "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    group = data["files"][0]["groups"][0]
    # a pathless Grep reaches the store; "unknown" alone is not an abstention
    assert group["grep_memory"]["k"] == 1
    assert group["correct"]["k"] == 0
    assert data["scoring_version"] == ae.SCORING_VERSION
    rescored = data["files"][0]["rescored"]
    assert rescored["changed_sessions"] == 1 and rescored["changed_fields"] >= 3
    assert "re-scored" in captured.err and "differ from the stored" in captured.err
    assert ae.main(["--summarize", str(path)]) == 0
    assert "re-scored" in capsys.readouterr().out.splitlines()[0]


def test_summarize_is_quiet_when_the_stored_metrics_agree(tmp_path, capsys):
    task = ae.load_tasks()[0]
    tools = [{"name": "Bash", "input": {"command": "lore search x"}, "error": False}]
    log = [{"event": "search", "query": "x", "hits": 1, "top": "p", "via": "cli"}]
    answer = "Pinned to 3.45.x."
    fresh = ae.metrics(task, tools, answer, log)
    row = {**session("include", "A"), **fresh, "tools": tools, "log": log, "answer": answer,
           "scoring_version": ae.SCORING_VERSION}
    path = tmp_path / "new.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert ae.main(["--summarize", str(path)]) == 0
    assert "re-scored" not in capsys.readouterr().out


def test_sessions_are_refused_on_windows(monkeypatch, capsys):
    monkeypatch.setattr(ae.sys, "platform", "win32")
    assert ae.main(["--dry-run", "--tasks", "A"]) == 2
    assert "POSIX" in capsys.readouterr().err
