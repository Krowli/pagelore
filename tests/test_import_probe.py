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
    # each other, which nothing cites.
    assert result["reach"] == pytest.approx(1 / 5)
    assert result["noise"][None]["median"] == pytest.approx(0.0)

    # page-ac cites two files; dropping either one still finds it through the
    # other, via the one-hop group around the dropped file.
    assert result["loo_cases"] == 2
    assert result["loo_recall"] == pytest.approx(1.0)
    assert result["loo_median_group"] == pytest.approx(1.5)


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
