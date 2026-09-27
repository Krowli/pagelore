"""`evals/import_probe.py` on a tiny synthetic repo with known edges and metrics.

Not a probe run — a correctness check on the resolver and the metric arithmetic,
small enough to stay fast.
"""
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "evals"))

import import_probe as ip  # noqa: E402

from pagelore import write as memory_write  # noqa: E402

FILLER = ("\n\nRecorded so the next agent does not rediscover it: the cause sits far "
          "from the symptom, the fix is two lines, and the alternative was rejected "
          "for a reason that is not visible in the code.\n")


@pytest.fixture()
def repo(tmp_path):
    """A tiny repo, tracked by git, with one Python, one TS and one Rust edge, and
    two memory pages: one citing a single file, one citing two."""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "web").mkdir()
    (root / "rust" / "src").mkdir(parents=True)

    (root / "pkg" / "a.py").write_text("from . import b\n", encoding="utf-8")
    (root / "pkg" / "b.py").write_text("", encoding="utf-8")
    (root / "pkg" / "c.py").write_text("import pkg.a\n", encoding="utf-8")

    (root / "web" / "x.ts").write_text("import { y } from './y';\n", encoding="utf-8")
    (root / "web" / "y.ts").write_text("", encoding="utf-8")

    (root / "rust" / "src" / "lib.rs").write_text("mod m;\n", encoding="utf-8")
    (root / "rust" / "src" / "m.rs").write_text("", encoding="utf-8")

    store = root / ".memory"
    store.mkdir()
    memory_write.write_page(store, "page-a", "About a.py", "concept",
                            ["pkg/a.py"], "## Context\n\nDescribes a.py." + FILLER)
    memory_write.write_page(store, "page-ac", "About a.py and c.py", "concept",
                            ["pkg/a.py", "pkg/c.py"],
                            "## Context\n\nDescribes both a.py and c.py." + FILLER)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def test_resolves_edges_per_language(repo):
    files = ip.list_repo_files(repo)
    code_files = [f for f in files
                  if f.endswith(".py") or f.endswith(ip.JS_EXTS) or f.endswith(".rs")]
    edges_out, stats = ip.build_graph(repo, code_files)

    assert edges_out["pkg/a.py"] == {"pkg/b.py"}
    assert edges_out["pkg/c.py"] == {"pkg/a.py"}
    assert edges_out["web/x.ts"] == {"web/y.ts"}
    assert edges_out["rust/src/lib.rs"] == {"rust/src/m.rs"}

    assert stats["python"] == {"seen": 2, "resolved": 2}
    assert stats["ts/js"] == {"seen": 1, "resolved": 1}
    assert stats["rust"] == {"seen": 1, "resolved": 1}


def test_absolute_from_import_prefers_submodule_over_package():
    """`from pkg import search` names pkg/search.py, not pkg/__init__.py — the
    bug this regression test guards: resolving to the package unconditionally
    dropped the real edge to the submodule."""
    code_set = {"pkg/__init__.py", "pkg/search.py"}
    targets, seen, resolved = ip.parse_python("app.py", "from pkg import search\n", code_set)
    assert targets == ["pkg/search.py"]
    assert (seen, resolved) == (1, 1)


def test_absolute_from_import_falls_back_to_package_for_a_plain_symbol():
    """`from pkg import CONFIG` where CONFIG is not a submodule falls back to
    pkg's own __init__.py, since that is where a symbol import actually lives."""
    code_set = {"pkg/__init__.py", "pkg/search.py"}
    targets, seen, resolved = ip.parse_python("app.py", "from pkg import CONFIG\n", code_set)
    assert targets == ["pkg/__init__.py"]
    assert (seen, resolved) == (1, 1)


def test_bare_relative_from_import_prefers_submodule_over_package():
    """`from . import search` inside pkg/app.py names pkg/search.py."""
    code_set = {"pkg/__init__.py", "pkg/search.py"}
    targets, _, _ = ip.parse_python("pkg/app.py", "from . import search\n", code_set)
    assert targets == ["pkg/search.py"]


def test_dotted_relative_from_import_prefers_submodule_over_module():
    """`from .sub import inner` inside pkg/app.py names pkg/sub/inner.py, a
    submodule of the sub *package*, not pkg/sub.py."""
    code_set = {"pkg/sub/__init__.py", "pkg/sub/inner.py"}
    targets, _, _ = ip.parse_python("pkg/app.py", "from .sub import inner\n", code_set)
    assert targets == ["pkg/sub/inner.py"]


def test_dotted_relative_from_import_falls_back_to_module_for_a_plain_symbol():
    """`from .sub import CONST` where sub is a plain module (pkg/sub.py, no
    submodule named CONST) falls back to pkg/sub.py itself."""
    code_set = {"pkg/sub.py"}
    targets, _, _ = ip.parse_python("pkg/app.py", "from .sub import CONST\n", code_set)
    assert targets == ["pkg/sub.py"]


def test_metrics_on_the_synthetic_repo(repo):
    files = ip.list_repo_files(repo)
    code_files = [f for f in files
                  if f.endswith(".py") or f.endswith(ip.JS_EXTS) or f.endswith(".rs")]
    result = ip.compute(repo, code_files)

    assert result["n_code_files"] == 7
    assert result["n_pages"] == 2

    # page-a cites a.py, page-ac cites a.py and c.py: two files cited directly
    assert result["coverage"] == pytest.approx(2 / 7)
    assert result["n_uncited"] == 5

    # b.py is one hop from the cited a.py; x.ts/y.ts and lib.rs/m.rs only reach
    # each other, which nothing cites. No file here is a hub (every in-degree
    # is 0 or 1), so every hub cap gives the same numbers.
    assert result["loo_cases"] == 2
    for cap in ip.HUB_CAPS:
        c = result["per_cap"][cap]
        assert c["reach"] == pytest.approx(1 / 5)
        # only b.py's group is non-empty (size 2: page-a and page-ac both cite a.py)
        assert c["median_nonempty"] == pytest.approx(2.0)
        # page-ac cites two files; dropping either one still finds it through
        # the other, via the one-hop group around the dropped file.
        assert c["loo_recall"] == pytest.approx(1.0)
        assert c["loo_median_group"] == pytest.approx(1.5)


def test_cli_runs_end_to_end(repo, capsys):
    argv = sys.argv
    sys.argv = ["import_probe.py", "--repo", str(repo)]
    try:
        assert ip.main() == 0
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "VERDICT:" in out
    assert "reach" in out.lower()


def test_hub_cap_flips_the_verdict(tmp_path):
    """A hub file's noise is exactly what a hub cap exists to drop: this repo
    fails the build threshold at cap inf and cap 10, and passes at cap 5,
    purely on the noise metric — reach and leave-one-out recall hold at every
    cap. hub.py is imported by 7 files (target.py + h1..h6.py): a hub at cap 5
    (7 > 5) but not at cap 10 (7 <= 10)."""
    root = tmp_path / "hubrepo"
    root.mkdir()
    (root / "hub.py").write_text("", encoding="utf-8")
    (root / "clean.py").write_text("", encoding="utf-8")
    (root / "target.py").write_text("import hub\nimport clean\n", encoding="utf-8")
    for i in range(1, 7):
        (root / f"h{i}.py").write_text("import hub\n", encoding="utf-8")
    # An independent, hub-free pair so leave-one-out has real, cap-proof cases.
    (root / "a.py").write_text("from . import b\n", encoding="utf-8")
    (root / "b.py").write_text("", encoding="utf-8")
    (root / "c.py").write_text("import a\n", encoding="utf-8")

    store = root / ".memory"
    store.mkdir()
    # Four distinct pages about hub.py: this is the noise a cap is meant to cut.
    for i in range(1, 5):
        memory_write.write_page(
            store, f"page-hub{i}", f"About hub.py, angle {i}", "concept", ["hub.py"],
            f"## Context\n\nDescribes hub.py from angle {i}." + FILLER)
    memory_write.write_page(store, "page-clean", "About clean.py", "concept",
                            ["clean.py"], "## Context\n\nDescribes clean.py." + FILLER)
    # Each hub importer is directly cited by its own page, so it does not
    # itself count as an uncited file competing for reach.
    for i in range(1, 7):
        memory_write.write_page(
            store, f"page-h{i}", f"About h{i}.py", "concept", [f"h{i}.py"],
            f"## Context\n\nDescribes h{i}.py, a hub importer." + FILLER)
    memory_write.write_page(store, "page-a", "About a.py", "concept",
                            ["a.py"], "## Context\n\nDescribes a.py." + FILLER)
    memory_write.write_page(store, "page-ac", "About a.py and c.py", "concept",
                            ["a.py", "c.py"],
                            "## Context\n\nDescribes both a.py and c.py." + FILLER)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)

    code_files = [f for f in ip.list_repo_files(root) if f.endswith(".py")]
    result = ip.compute(root, code_files)

    # target.py and b.py are the only uncited files; a.py/c.py's leave-one-out
    # pair is the only source of LOO cases.
    assert result["n_uncited"] == 2
    assert result["loo_cases"] == 2

    assert result["per_cap"][None]["pass"] is False
    assert result["per_cap"][10]["pass"] is False
    assert result["per_cap"][5]["pass"] is True

    # reach and recall hold everywhere; only noise flips.
    for cap in ip.HUB_CAPS:
        assert result["per_cap"][cap]["reach"] == pytest.approx(1.0)
        assert result["per_cap"][cap]["loo_recall"] == pytest.approx(1.0)
    assert result["per_cap"][None]["median_nonempty"] == pytest.approx(3.5)
    assert result["per_cap"][10]["median_nonempty"] == pytest.approx(3.5)
    assert result["per_cap"][5]["median_nonempty"] == pytest.approx(1.5)

    assert "VERDICT: build (hub cap 5)" in ip.render(result, root)
