import json

import pytest

from pagelore import lib as memory_lib
from pagelore import write as memory_write

LONG = ("The reap loop waits on the child before closing the master fd, so a child "
        "that ignores SIGTERM keeps the fd open and waitpid never returns. " * 3)


def test_creates_page_with_frontmatter(store):
    p = memory_write.write_page(store, "a-slug", "A title", "note", [], "## H\n\nbody\n")
    page = memory_lib.parse_page(p)
    assert page.slug == "a-slug"
    assert page.title == "A title"
    assert page.meta["kind"] == "note"


def test_rejects_bad_slug(store):
    with pytest.raises(ValueError):
        memory_write.write_page(store, "Bad Slug", "t", "note", [], "x")


def test_rerun_replaces_same_section(store):
    memory_write.write_page(store, "s", "t", "note", [], "## Cause\n\nfirst\n")
    p = memory_write.write_page(store, "s", "t", "note", [], "## Cause\n\nsecond\n")
    body = memory_lib.parse_page(p).body
    assert "second" in body and "first" not in body


def test_rerun_appends_new_section(store):
    memory_write.write_page(store, "s", "t", "note", [], "## Cause\n\nfirst\n")
    p = memory_write.write_page(store, "s", "t", "note", [], "## Fix\n\napplied\n")
    body = memory_lib.parse_page(p).body
    assert "first" in body and "applied" in body


def test_sources_accumulate(store):
    memory_write.write_page(store, "s", "t", "note", ["a.ts"], "x")
    p = memory_write.write_page(store, "s", "t", "note", ["b.ts"], "x")
    assert memory_lib.parse_page(p).meta["sources"] == ["a.ts", "b.ts"]


def test_identical_rewrite_keeps_updated_and_does_not_touch_the_file(store, monkeypatch):
    """A second write with the exact same slug/title/kind/sources/body must not
    bump `updated` or rewrite the file — otherwise a no-op re-run "refreshes" a
    page that, in substance, nobody touched (see the staleness check this feeds)."""
    real_date = memory_write._dt.date
    days = iter(["2026-01-01", "2026-01-02"])

    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return real_date.fromisoformat(next(days))

    monkeypatch.setattr(memory_write._dt, "date", FakeDate)

    p = memory_write.write_page(store, "s", "t", "note", ["a.ts"], "## Cause\n\nsame\n")
    first_meta = memory_lib.parse_page(p).meta
    first_mtime = p.stat().st_mtime_ns

    p2 = memory_write.write_page(store, "s", "t", "note", ["a.ts"], "## Cause\n\nsame\n")
    second_meta = memory_lib.parse_page(p2).meta
    second_mtime = p2.stat().st_mtime_ns

    assert first_meta["updated"] == "2026-01-01"
    assert second_meta["updated"] == "2026-01-01"  # not bumped to 2026-01-02
    assert second_mtime == first_mtime  # file was not written a second time


def test_main_reports_unchanged_on_an_identical_rerun(tmp_path, capsys):
    """CLI boundary: a repeat of the exact same write prints the `unchanged:`
    line instead of `replaced:`/`appended:`, still exits 0, still prints the
    path, and logs `mode="unchanged"` so `lore stats` can count it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.ts").write_text("export {}")
    store = tmp_path / ".memory"
    store.mkdir()
    argv = ["--store", str(store), "--slug", "pty-hangs-on-exit", "--title", "PTY hangs",
            "--kind", "bug", "--source", "src/real.ts", "--body", LONG]

    assert memory_write.main(argv) == 0
    capsys.readouterr()

    rc = memory_write.main(argv)
    out, err = capsys.readouterr()
    assert rc == 0
    assert "unchanged: nothing to write" in err
    assert "replaced:" not in err
    assert str(store / "pty-hangs-on-exit.md") in out

    log_line = (store / memory_lib.LOG_NAME).read_text(encoding="utf-8").splitlines()[-1]
    assert json.loads(log_line)["mode"] == "unchanged"


def _write_argv(store, body=LONG):
    return ["--store", str(store), "--slug", "pty-hangs-on-exit", "--title", "PTY hangs",
            "--kind", "bug", "--source", "src/real.ts", "--body", body]


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.ts").write_text("export {}")
    store = tmp_path / ".memory"
    store.mkdir()
    return store


def test_rewrite_survives_a_non_utf8_byte_in_the_existing_page(repo):
    """HEAD 0f9284d wrote a page with a stray non-UTF-8 byte in it fine. The
    identical-rewrite comparison must not regress that: a strict
    `path.read_text(encoding="utf-8")` raises UnicodeDecodeError instead of the
    tolerant `lib.read_text` (errors="replace") every other read in the store
    already uses."""
    argv = _write_argv(repo)
    assert memory_write.main(argv) == 0

    path = repo / "pty-hangs-on-exit.md"
    with path.open("ab") as fh:
        fh.write(b"\xe9\xf2")  # not valid UTF-8 on its own

    rc = memory_write.main(argv)  # must not raise UnicodeDecodeError
    assert rc == 0


def test_main_trusts_write_pages_own_unchanged_decision(repo, monkeypatch, capsys):
    """main() must read write_page's module-level decision, not re-derive it
    from a second, unlocked before/after file read of its own — a concurrent
    writer between two such reads could make main() disagree with what
    write_page actually did. Proven here by forcing the flag directly: even
    though this call is a brand-new page (nothing could honestly be
    "unchanged"), main() reports exactly what write_page's flag says."""
    argv = _write_argv(repo)
    real_write_page = memory_write.write_page

    def fake_write_page(*args, **kwargs):
        path = real_write_page(*args, **kwargs)
        memory_write.last_unchanged = True
        return path

    monkeypatch.setattr(memory_write, "write_page", fake_write_page)
    rc = memory_write.main(argv)
    err = capsys.readouterr().err
    assert rc == 0
    assert "unchanged: nothing to write" in err


def test_main_never_reports_unchanged_for_a_real_change(repo, capsys):
    assert memory_write.main(_write_argv(repo)) == 0
    capsys.readouterr()

    changed_body = LONG + " One more sentence, changed."
    rc = memory_write.main(_write_argv(repo, changed_body))
    err = capsys.readouterr().err
    assert rc == 0
    assert "unchanged" not in err
    assert "changed" in memory_lib.parse_page(repo / "pty-hangs-on-exit.md").body
