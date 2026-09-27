"""Refusals and searches are recorded, so a trial ends in numbers.

The failure this guards against is the one the design already cites: a check
whose result nobody collects is indistinguishable from no check. Without a log
there is no way to answer "how often did the gate fire, and on what" except by
memory.
"""
import json

import pytest

from pagelore import lib as memory_lib
from pagelore import search as memory_search
from pagelore import write as memory_write

LONG = ("The reap loop waits on the child before closing the master fd, so a child "
        "that ignores SIGTERM keeps the fd open and waitpid never returns. " * 3)


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.ts").write_text("export {}")
    (tmp_path / ".memory").mkdir()
    return tmp_path


def entries(repo):
    path = repo / ".memory" / memory_lib.LOG_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(repo, *args, body=LONG):
    argv = ["--store", str(repo / ".memory")]
    if body is not None:
        argv += ["--body", body]
    return memory_write.main([*argv, *args])


def test_successful_write_is_logged(repo):
    write(repo, "--slug", "good-page", "--title", "T", "--kind", "bug", "--source", "src/real.ts")
    (e,) = entries(repo)
    assert e["event"] == "write"
    assert e["slug"] == "good-page"
    assert e["ts"]


def test_refusal_is_logged_with_a_countable_code(repo):
    write(repo, "--slug", "no-src", "--title", "T", "--kind", "bug")
    (e,) = entries(repo)
    assert e["event"] == "reject"
    assert e["code"] == "no_sources"


@pytest.mark.parametrize("args,body,code", [
    (["--slug", "a", "--title", "T", "--kind", "bug"], LONG, "no_sources"),
    (["--slug", "b", "--title", "T", "--kind", "bug", "--source", "src/nope.ts"], LONG,
     "source_missing"),
    (["--slug", "c", "--title", "T", "--kind", "bug", "--source", "src/real.ts"], "short",
     "body_too_short"),
    (["--slug", "d", "--title", "T", "--kind", "nope", "--source", "src/real.ts"], LONG,
     "bad_kind"),
    (["--slug", "E_E", "--title", "T", "--kind", "bug", "--source", "src/real.ts"], LONG,
     "bad_slug"),
    (["--slug", "f", "--title", "T", "--kind", "bug", "--source", "src/real.ts"], None,
     "no_body"),
    (["--slug", "g", "--title", "T", "--kind", "bug", "--source", "src/real.ts"],
     LONG + "\nAKIA1234567890ABCDEF", "secret_in_body"),
])
def test_every_refusal_reason_has_its_own_code(repo, args, body, code):
    assert write(repo, *args, body=body) == 1
    assert entries(repo)[-1]["code"] == code


def test_a_high_entropy_write_logs_its_warning_code(repo):
    body = LONG + "\nZk3x9QpL2vB8mR7tN0yC5wJ1hU4sD6eA9gT3iX7oV2z"
    write(repo, "--slug", "warn-page", "--title", "T", "--kind", "bug",
          "--source", "src/real.ts", body=body)
    e = entries(repo)[-1]
    assert e["event"] == "write"
    assert e["warnings"] == ["high_entropy"]


def test_a_clean_write_has_no_warnings_field(repo):
    write(repo, "--slug", "clean-page", "--title", "T", "--kind", "bug",
          "--source", "src/real.ts")
    assert "warnings" not in entries(repo)[-1]


def test_search_is_logged_with_hit_count(repo):
    write(repo, "--slug", "pty-hangs", "--title", "PTY hangs", "--kind", "bug",
          "--source", "src/real.ts")
    memory_search.search("pty hangs", repo / ".memory")
    e = entries(repo)[-1]
    assert e["event"] == "search"
    assert e["query"] == "pty hangs"
    assert e["hits"] >= 1
    assert e["top"] == "pty-hangs"


def test_search_with_no_hits_is_still_logged(repo):
    memory_search.search("kubernetes helm chart", repo / ".memory")
    e = entries(repo)[-1]
    assert e["event"] == "search"
    assert e["hits"] == 0
    assert e["top"] is None


def test_logging_never_breaks_the_operation(repo, monkeypatch):
    """A log that can take the tool down with it is worse than no log.

    Only the serialisation inside log_event is broken here — patching something
    broader (Path.open) would also break the page write and prove nothing.
    """
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(memory_lib.json, "dumps", boom)

    rc = write(repo, "--slug", "still-works", "--title", "T", "--kind", "bug",
               "--source", "src/real.ts")
    assert rc == 0
    assert (repo / ".memory" / "still-works.md").is_file()

    monkeypatch.undo()
    assert entries(repo) == [], "the failed log write must not leave a partial line"


def test_store_shields_its_log_from_git(repo):
    """Even in `tracked` store mode the log must not land in a commit: it holds
    every query anyone typed."""
    write(repo, "--slug", "any-page", "--title", "T", "--kind", "bug", "--source", "src/real.ts")
    ignore = (repo / ".memory" / ".gitignore").read_text()
    assert memory_lib.LOG_NAME in ignore


def test_the_session_is_recorded_when_the_harness_names_one(repo, monkeypatch):
    """Claude Code exports the session id to the Bash tool, which is where the
    write runs. With it in the record, "did this session search and never write"
    is a question the log can answer with no hook anywhere."""
    monkeypatch.setenv(memory_lib.SESSION_ENV, "abc-123")
    write(repo, "--slug", "in-session", "--title", "T", "--kind", "bug", "--source", "src/real.ts")
    assert entries(repo)[-1]["session"] == "abc-123"

    monkeypatch.delenv(memory_lib.SESSION_ENV)
    write(repo, "--slug", "no-session", "--title", "T", "--kind", "bug", "--source", "src/real.ts")
    assert "session" not in entries(repo)[-1]
