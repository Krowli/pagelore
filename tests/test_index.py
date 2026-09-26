"""The FTS5 index is a cache, and a cache is a new way to be wrong.

Every test here is a way the index could answer differently from reading the
markdown, or refuse to answer at all. The rule it has to obey is one sentence: the
pages are the memory, the index only says which file to open, and any doubt at all
falls back to reading the pages.
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import conftest
import pytest

from pagelore import index as memory_index
from pagelore import search as memory_search
from pagelore import write as memory_write

SRC = Path(__file__).resolve().parents[1] / "src" / "pagelore"
SEARCH = [*conftest.LORE, "search"]

LONG = ("The reap loop waits on the child before closing the master fd, so a child "
        "that ignores SIGTERM keeps the fd open and waitpid never returns. " * 3)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Never touch the developer's real ~/.cache, and never share an index between
    two tests."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.delenv(memory_index.DISABLE_ENV, raising=False)


@pytest.fixture()
def stocked(store):
    memory_write.write_page(store, "webgl-context-loss",
                            "xterm WebGL context loss on display sleep", "bug", [],
                            "## Cause\n\n" + LONG)
    memory_write.write_page(store, "pty-reap-loop", "The PTY reap loop hangs on exit",
                            "bug", [], "## Cause\n\nwaitpid never returns. " + LONG)
    memory_write.write_page(store, "store-privacy", "The store shields itself at creation",
                            "decision", [], "## Decision\n\ngitignore at creation. " + LONG)
    return store


def slugs(store, query="webgl context loss"):
    return [p.slug for _, p in memory_search.search(query, store)]


def scan_slugs(store, query, monkeypatch):
    monkeypatch.setenv(memory_index.DISABLE_ENV, "1")
    try:
        return [p.slug for _, p in memory_search.search(query, store)]
    finally:
        monkeypatch.delenv(memory_index.DISABLE_ENV, raising=False)


def test_fts5_is_available_here():
    """If this fails the rest of the file is testing the fallback by accident."""
    assert memory_index.fts5_available()


def test_the_index_is_not_written_into_the_store(stocked):
    """In `tracked` mode anything inside the store is committed, and a store made
    before this feature existed would never get a new .gitignore line."""
    slugs(stocked)
    added = {p.name for p in stocked.iterdir()}
    assert not any(name.endswith((".db", ".db-journal", ".db-wal", ".db-shm"))
                   for name in added), added
    assert memory_index.index_path(stocked).exists()


def test_a_symlinked_store_and_its_target_share_one_index(tmp_path):
    """`lore init --store home` puts the pages in ~/.pagelore/<project> and
    symlinks .memory at it. Keying on the unresolved path would index twice."""
    real = tmp_path / "real-store"
    real.mkdir()
    link = tmp_path / ".memory"
    link.symlink_to(real)
    assert memory_index.index_path(link) == memory_index.index_path(real)


def test_both_paths_find_the_same_pages_and_agree_on_the_best_one(stocked, monkeypatch):
    """What the two paths actually guarantee.

    They are different formulas — FTS5's per-column BM25 against this project's
    BM25F — so the order of the low-scoring tail can differ, and the evaluation
    says that difference is not a quality difference (nDCG@10 0.644 against 0.652,
    interval across zero). What must hold is that neither path invents or loses a
    page, and that they agree on the hit the agent will actually read."""
    for query in ("webgl context loss", "waitpid reap loop", "gitignore privacy store",
                  "display sleep renderer", "нет такого запроса"):
        indexed = slugs(stocked, query)
        scanned = scan_slugs(stocked, query, monkeypatch)
        assert set(indexed) == set(scanned), query
        assert indexed[:1] == scanned[:1], query


def test_the_search_says_which_path_answered(stocked, monkeypatch):
    slugs(stocked)
    assert memory_search.last_path == "index"
    scan_slugs(stocked, "webgl", monkeypatch)
    assert memory_search.last_path == "scan"


def test_editing_a_page_invalidates_the_index(stocked):
    assert "webgl-context-loss" in slugs(stocked)
    page = stocked / "webgl-context-loss.md"
    page.write_text(page.read_text(encoding="utf-8").replace("WebGL", "ZZZUNIQUE"),
                    encoding="utf-8")
    assert "webgl-context-loss" in slugs(stocked, "zzzunique")


def test_a_restored_mtime_does_not_hide_a_content_change(stocked):
    """`tar -xp`, `rsync -a` and `cp -p` put the old mtime back. Only the inode and
    ctime catch an equal-sized rewrite underneath a restored timestamp."""
    page = stocked / "pty-reap-loop.md"
    original = page.read_text(encoding="utf-8")
    before = page.stat()
    slugs(stocked)  # build the index against the original

    replacement = original.replace("waitpid never returns", "waitpid never RETURNZ")
    assert len(replacement) == len(original)
    swap = page.with_suffix(".md.new")
    swap.write_text(replacement, encoding="utf-8")
    os.replace(swap, page)
    os.utime(page, ns=(before.st_atime_ns, before.st_mtime_ns))

    assert "pty-reap-loop" in slugs(stocked, "returnz")


def test_a_deleted_page_stops_being_returned(stocked):
    assert "store-privacy" in slugs(stocked, "gitignore privacy")
    (stocked / "store-privacy.md").unlink()
    assert "store-privacy" not in slugs(stocked, "gitignore privacy")


@pytest.mark.parametrize("damage", ["garbage", "truncated"])
def test_a_corrupt_index_is_repaired_not_merely_survived(stocked, damage):
    """Answering around a corrupt index is only half of it. If the damage is not
    also repaired, every later search pays the full scan forever while a broken
    file sits in the cache — working, and quietly slow."""
    slugs(stocked)
    path = memory_index.index_path(stocked)
    if damage == "garbage":
        path.write_bytes(b"this is not a database at all")
    else:
        path.write_bytes(path.read_bytes()[:200])

    assert "webgl-context-loss" in slugs(stocked)
    assert "webgl-context-loss" in slugs(stocked)
    assert memory_search.last_path == "index", "the damaged index was never rebuilt"


def test_an_index_that_passes_its_freshness_check_and_then_fails_the_query(stocked):
    """The other half of "corrupt": a file whose metadata is intact and current, so
    the freshness check passes, and whose table is gone by the time the query runs.
    A truncated or garbage file never reaches that branch — it fails at open — so
    without this the outer failure path was defensive code nothing exercised."""
    slugs(stocked)
    import sqlite3
    conn = sqlite3.connect(memory_index.index_path(stocked))
    try:
        conn.execute("DROP TABLE pages")
        conn.commit()
    finally:
        conn.close()
    assert "webgl-context-loss" in slugs(stocked)


def test_a_bumped_tokenizer_version_rebuilds(stocked, monkeypatch):
    """The index stores the output of tokenize(). A change to it without a rebuild
    is zero recall with no error anywhere."""
    slugs(stocked)
    path = memory_index.index_path(stocked)
    monkeypatch.setattr(memory_index, "TOKENIZER_VERSION",
                        memory_index.TOKENIZER_VERSION + 1)
    stamp_before = path.stat().st_mtime_ns
    assert "webgl-context-loss" in slugs(stocked)
    assert path.stat().st_mtime_ns != stamp_before


@conftest.needs_posix
def test_a_read_only_store_is_still_searchable(stocked):
    """A search must never need to write the store it is reading."""
    slugs(stocked)
    stocked.chmod(0o500)
    try:
        assert "webgl-context-loss" in slugs(stocked)
    finally:
        stocked.chmod(0o700)


@conftest.needs_posix
def test_a_read_only_store_with_no_index_yet_still_answers(stocked):
    """The harder half: nothing cached, and the builder cannot even create its lock.
    That must degrade to reading the markdown, not report 'someone else is
    building' and answer with nothing."""
    memory_index.forget(stocked)
    stocked.chmod(0o500)
    try:
        assert "webgl-context-loss" in slugs(stocked)
    finally:
        stocked.chmod(0o700)


def test_disabling_fts5_by_environment_still_searches(stocked, monkeypatch):
    """The switch CI needs to exercise the fallback, which otherwise never runs on
    any machine that has FTS5 — which is all of them."""
    monkeypatch.setenv(memory_index.DISABLE_ENV, "1")
    assert "webgl-context-loss" in slugs(stocked)
    assert not memory_index.index_path(stocked).exists()


def test_parallel_cold_searches_all_answer(stocked):
    """Twenty searches onto a cold index gave eleven 'database is locked' failures
    before the builder was elected without waiting — and a naive fix had nineteen
    of twenty silently answer from an index that was still being written."""
    memory_index.forget(stocked)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: slugs(stocked), range(20)))
    assert all("webgl-context-loss" in r for r in results), results


def test_a_stale_builder_lock_does_not_freeze_the_index(stocked):
    memory_index.forget(stocked)
    lock = stocked / memory_index.BUILD_LOCK
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock.write_text(f"{dead.pid} {memory_index._boot_id()}", encoding="utf-8")
    assert "webgl-context-loss" in slugs(stocked)


def test_a_hostile_entry_is_neither_indexed_nor_a_permanent_rebuild(stocked):
    """identity() and the index both come from page_paths(), so the security filter
    is inherited rather than reimplemented."""
    secret = stocked.parent / ".env"
    secret.write_text("AWS_SECRET_ACCESS_KEY=hunter2\n")
    (stocked / "env-notes.md").symlink_to(secret)
    assert memory_search.search("secret access key hunter2", stocked) == []
    fingerprint = memory_index.identity(stocked)
    assert "env-notes.md" not in fingerprint


@pytest.mark.parametrize("name", ["lib.py", "search.py", "write.py",
                                  "stats.py", "index.py"])
def test_sqlite3_is_never_imported_at_module_scope(name):
    """Debian's python3-minimal ships no sqlite3 module at all, so a top-level
    import turns a working search into a traceback on every session-start hook."""
    for line in (SRC / name).read_text(encoding="utf-8").splitlines():
        assert not line.startswith("import sqlite3"), f"{name}: {line}"
        assert not line.startswith("from sqlite3"), f"{name}: {line}"


def test_the_index_records_what_it_was_built_from(stocked):
    slugs(stocked)
    import sqlite3
    conn = sqlite3.connect(memory_index.index_path(stocked))
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()
    assert int(meta["schema_version"]) == memory_index.SCHEMA_VERSION
    assert int(meta["tokenizer_version"]) == memory_index.TOKENIZER_VERSION
    assert meta["identity"] == memory_index.digest(memory_index.identity(stocked))
