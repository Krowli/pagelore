"""`lore search` and `lore show` mark a page whose `sources` moved on after it.

Git commit time is the clock, for both the page file and its sources — a fresh
clone makes every mtime new, and `updated` in the frontmatter is day-granular and
written before the commit exists. No git reachable at all (no repo, no binary, a
timeout) means no markers at all, not a guess: `gone` needs the project root to
resolve a source, and without git there is no way to find it reliably from
wherever the command happens to run.
"""
from __future__ import annotations

import locale
import os
import subprocess
from pathlib import Path

import pytest

from pagelore import freshness, lib
from pagelore import search as memory_search
from pagelore import write as memory_write

FILLER = ("\n\nRecorded so the next agent does not rediscover it: the cause sits far "
          "from the symptom, the fix is two lines, and the alternative was rejected "
          "for a reason that is not visible in the code.\n")


@pytest.fixture()
def repo(tmp_path):
    """A fresh git repo, with a local identity so a commit never asks the real user."""
    root = tmp_path / "project"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "a@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    return root


def commit(root, rel_paths, when, content=None):
    """Write and commit one or more root-relative paths together, at an exact date.

    `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` rather than a sleep: two commits a
    second apart would make the suite slow and still leave the ordering to luck
    on a slow runner.
    """
    if isinstance(rel_paths, str):
        rel_paths = [rel_paths]
    for rel in rel_paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content is not None else f"{rel} @ {when}", encoding="utf-8")
    subprocess.run(["git", "add", *rel_paths], cwd=root, check=True)
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    subprocess.run(["git", "commit", "-q", "-m", f"commit {rel_paths}"], cwd=root,
                   check=True, env=env)


def write_page(store, slug, sources, title=None):
    memory_write.write_page(store, slug, title or slug.replace("-", " "), "bug",
                            sources, "## Cause\n\nWhy this happened." + FILLER)


def commit_page(root, store, slug, when):
    commit(root, f"{store.name}/{slug}.md", when,
           content=(store / f"{slug}.md").read_text(encoding="utf-8"))


def test_source_committed_after_the_page_is_marked_changed(repo):
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/a.py"])
    commit_page(repo, store, "p", "2020-01-02T00:00:00")
    commit(repo, "src/a.py", "2020-01-03T00:00:00")

    result = freshness.drift(lib.load_pages(store), store)
    assert result == {"p": {"changed": ["src/a.py"], "gone": []}}


def test_page_and_source_in_the_same_commit_is_not_marked(repo):
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/a.py"])
    # Page and source land in one commit: same clock reading, no drift.
    commit(repo, ["src/a.py", f"{store.name}/p.md"], "2020-01-02T00:00:00")

    result = freshness.drift(lib.load_pages(store), store)
    assert result == {}


def test_not_a_git_repo_gives_no_markers_and_no_error(tmp_path):
    store = tmp_path / ".memory"
    store.mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    write_page(store, "p", ["src/a.py"])

    assert freshness.drift(lib.load_pages(store), store) == {}


def test_git_binary_missing_gives_no_markers_and_no_error(repo, monkeypatch):
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/a.py"])
    commit_page(repo, store, "p", "2020-01-02T00:00:00")

    def raiser(*a, **k):
        raise FileNotFoundError("git not found")
    monkeypatch.setattr(freshness.subprocess, "run", raiser)

    assert freshness.drift(lib.load_pages(store), store) == {}


def test_removed_source_is_gone(repo):
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/a.py"])
    commit_page(repo, store, "p", "2020-01-02T00:00:00")
    (repo / "src" / "a.py").unlink()

    result = freshness.drift(lib.load_pages(store), store)
    assert result == {"p": {"changed": [], "gone": ["src/a.py"]}}


def test_uncommitted_page_skips_changed_but_still_reports_gone(repo):
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    commit(repo, "src/b.py", "2020-01-01T00:00:00")
    # The page itself is written but never committed.
    write_page(store, "p", ["src/a.py", "src/b.py"])
    commit(repo, "src/a.py", "2020-01-03T00:00:00")
    (repo / "src" / "b.py").unlink()

    result = freshness.drift(lib.load_pages(store), store)
    # No page commit to compare against, so "changed" cannot fire for src/a.py —
    # but "gone" needs no page commit at all, only that git itself answered.
    assert result == {"p": {"changed": [], "gone": ["src/b.py"]}}


def test_uncommitted_source_edits_are_ignored(repo):
    """Drift is decided from commit history, never from the working tree — an
    edit nobody committed yet must not flip the marker on or off."""
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/a.py"])
    commit_page(repo, store, "p", "2020-01-02T00:00:00")
    commit(repo, "src/a.py", "2020-01-03T00:00:00")
    before = freshness.drift(lib.load_pages(store), store)

    (repo / "src" / "a.py").write_text("edited, never committed", encoding="utf-8")
    after = freshness.drift(lib.load_pages(store), store)

    assert before == after == {"p": {"changed": ["src/a.py"], "gone": []}}


def test_store_in_a_repo_subdirectory(tmp_path):
    """A monorepo: the git top-level is above the project root the store lives
    under. Pathspecs and `--name-only` output must be made comparable, or every
    source in a subdirectory project reads as touching nothing."""
    top = tmp_path / "monorepo"
    top.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=top, check=True)
    subprocess.run(["git", "config", "user.email", "a@example.com"], cwd=top, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=top, check=True)
    root = top / "apps" / "pagelore"
    root.mkdir(parents=True)
    store = root / ".memory"
    store.mkdir()

    def commit_at_top(rel_to_root, when):
        path = root / rel_to_root
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{rel_to_root} @ {when}", encoding="utf-8")
        rel_to_top = str((root / rel_to_root).relative_to(top))
        subprocess.run(["git", "add", rel_to_top], cwd=top, check=True)
        env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run(["git", "commit", "-q", "-m", rel_to_top], cwd=top, check=True, env=env)

    commit_at_top("src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/a.py"])
    page_text = (store / "p.md").read_text(encoding="utf-8")
    (root / ".memory" / "p.md").write_text(page_text, encoding="utf-8")
    rel_page = str((store / "p.md").relative_to(top))
    subprocess.run(["git", "add", rel_page], cwd=top, check=True)
    env = {**os.environ, "GIT_AUTHOR_DATE": "2020-01-02T00:00:00",
           "GIT_COMMITTER_DATE": "2020-01-02T00:00:00"}
    subprocess.run(["git", "commit", "-q", "-m", "page"], cwd=top, check=True, env=env)
    commit_at_top("src/a.py", "2020-01-03T00:00:00")

    result = freshness.drift(lib.load_pages(store), store)
    assert result == {"p": {"changed": ["src/a.py"], "gone": []}}


def test_a_nonascii_source_name_is_still_matched(repo):
    """`git log --name-only` quotes a non-ASCII byte as a C-style octal escape by
    default (`"src/caf\\303\\251.py"`), which never equals the plain string a page
    cites — so `changed` would silently never fire for such a source without
    `-c core.quotePath=false`."""
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/café.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["src/café.py"])
    commit_page(repo, store, "p", "2020-01-02T00:00:00")
    commit(repo, "src/café.py", "2020-01-03T00:00:00")

    result = freshness.drift(lib.load_pages(store), store)
    assert result == {"p": {"changed": ["src/café.py"], "gone": []}}


def test_a_dot_slash_prefixed_source_is_still_matched(repo):
    """`write.validate` accepts `./src/a.py` (it only checks the target exists),
    but `--name-only` prints the file as `src/a.py` — the two spellings must be
    one lookup key, or `changed` never fires for a source cited this way. The
    page still shows the source exactly as it was cited."""
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "p", ["./src/a.py"])
    commit_page(repo, store, "p", "2020-01-02T00:00:00")
    commit(repo, "src/a.py", "2020-01-03T00:00:00")

    result = freshness.drift(lib.load_pages(store), store)
    assert result == {"p": {"changed": ["./src/a.py"], "gone": []}}


def test_output_bytes_invalid_for_the_locale_encoding_do_not_crash(monkeypatch):
    """`core.quotePath=false` makes git emit raw UTF-8 path bytes instead of
    C-style octal escapes. On a non-UTF-8 locale (`cp1252`, still the Windows
    default on many installs), letting `subprocess.run` decode with `text=True`
    alone picks the locale's encoding — and a real UTF-8 path can be invalid
    there, raising `UnicodeDecodeError` (a `ValueError`, not caught by
    `except (OSError, subprocess.TimeoutExpired)`), crashing the caller instead
    of falling back to no markers.

    `subprocess.run` itself is replaced with a fake that decodes a fixed raw
    payload exactly the way the real one would given the keyword arguments
    `last_commits` actually passes — through `encoding=`/`errors=` if given, else
    through the ambient locale, the same contract `io.TextIOWrapper` uses for
    `text=True` with no explicit `encoding`. The payload is a real path,
    "Łukasz.py" (UTF-8: `\\xc5\\x81ukasz.py`), which decodes cleanly as UTF-8 but
    not as cp1252: byte `0x81` is unassigned there.
    """
    raw = "\x001600000000\n\nŁukasz.py\n".encode()

    def fake_run(cmd, **kwargs):
        if "encoding" in kwargs:
            stdout = raw.decode(kwargs["encoding"], errors=kwargs.get("errors", "strict"))
        else:
            stdout = raw.decode(locale.getpreferredencoding(False))
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(freshness.subprocess, "run", fake_run)
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp1252")

    assert freshness.last_commits(Path("."), ["Łukasz.py"]) == {"Łukasz.py": 1600000000}


def test_markers_do_not_leak_between_two_consecutive_searches(repo):
    """MCP runs in one long-lived process: a query with drift must not still be
    on `last_drift` when the next, unrelated query comes back with none. Titles
    and queries share no word with each other or with the common filler body, so
    each query matches exactly the one page it names."""
    store = repo / ".memory"
    store.mkdir()
    commit(repo, "src/a.py", "2020-01-01T00:00:00")
    write_page(store, "widget-latency-issue", ["src/a.py"])
    commit_page(repo, store, "widget-latency-issue", "2020-01-02T00:00:00")
    commit(repo, "src/a.py", "2020-01-03T00:00:00")
    write_page(store, "kernel-panic-report", [])

    stale_hits = memory_search.search("widget latency", store)
    assert [p.slug for _, p in stale_hits] == ["widget-latency-issue"]
    memory_search.annotate(stale_hits, store)
    assert memory_search.last_drift.get("widget-latency-issue", {}).get("changed") \
        == ["src/a.py"]

    fresh_hits = memory_search.search("kernel panic", store)
    assert [p.slug for _, p in fresh_hits] == ["kernel-panic-report"]
    memory_search.annotate(fresh_hits, store)
    assert "widget-latency-issue" not in memory_search.last_drift
