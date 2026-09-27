"""memory_stats reads the log back. Without it the log is write-only, which is
the same failure the write gate exists to avoid."""
import json

import pytest

from pagelore import lib as memory_lib
from pagelore import stats as memory_stats


@pytest.fixture()
def logged(tmp_path):
    store = tmp_path / ".memory"
    store.mkdir()
    for event in [
        {"event": "write", "slug": "a", "mode": "create", "chars": 400},
        {"event": "write", "slug": "a", "mode": "merge", "chars": 600},
        {"event": "reject", "code": "no_sources", "slug": "b"},
        {"event": "reject", "code": "no_sources", "slug": "c"},
        {"event": "reject", "code": "body_too_short", "slug": "d"},
        {"event": "search", "query": "pty hangs", "hits": 3, "top": "a"},
        {"event": "search", "query": "kubernetes", "hits": 0, "top": None},
    ]:
        memory_lib.log_event(store, event.pop("event"), **event)
    return store


def test_counts_writes_refusals_and_searches(logged):
    s = memory_stats.summarise(memory_stats.read_log(logged, None))
    assert (s["writes"], s["creates"], s["merges"]) == (2, 1, 1)
    assert s["rejects"] == 3
    assert s["searches"] == 2


def test_reject_rate_is_a_share_of_attempts_not_of_everything(logged):
    """3 refusals against 5 write attempts — searches must not dilute it."""
    s = memory_stats.summarise(memory_stats.read_log(logged, None))
    assert s["reject_rate"] == 0.6


def test_groups_refusals_by_code(logged):
    s = memory_stats.summarise(memory_stats.read_log(logged, None))
    assert s["reject_codes"] == {"no_sources": 2, "body_too_short": 1}


def test_warn_codes_are_grouped_like_reject_codes(tmp_path):
    store = tmp_path / ".memory"
    store.mkdir()
    for event in [
        {"event": "write", "slug": "a", "mode": "create", "chars": 400,
         "warnings": ["high_entropy"]},
        {"event": "write", "slug": "b", "mode": "create", "chars": 400,
         "warnings": ["high_entropy"]},
        {"event": "write", "slug": "c", "mode": "create", "chars": 400},
    ]:
        memory_lib.log_event(store, event.pop("event"), **event)
    s = memory_stats.summarise(memory_stats.read_log(store, None))
    assert s["warn_codes"] == {"high_entropy": 2}


def test_warn_codes_are_printed_next_to_reject_codes(tmp_path, capsys):
    store = tmp_path / ".memory"
    store.mkdir()
    memory_lib.log_event(store, "write", slug="a", mode="create", chars=400,
                          warnings=["high_entropy"])
    memory_stats.main(["--store", str(store)])
    assert "high_entropy" in capsys.readouterr().out


def test_surfaces_the_queries_that_found_nothing(logged):
    s = memory_stats.summarise(memory_stats.read_log(logged, None))
    assert s["zero_hit_searches"] == 1
    assert s["zero_hit_queries"] == ["kubernetes"]


def test_since_filters_by_date(logged):
    assert memory_stats.read_log(logged, "2099-01-01") == []
    assert memory_stats.read_log(logged, "2000-01-01") != []


def test_a_torn_line_does_not_hide_the_rest(logged):
    """A crash mid-append leaves half a line; the log must still be readable."""
    with (logged / memory_lib.LOG_NAME).open("a", encoding="utf-8") as fh:
        fh.write('{"event": "write", "slug": "trunc')
    records = memory_stats.read_log(logged, None)
    assert len(records) == 7


def test_empty_store_reports_instead_of_crashing(tmp_path, capsys):
    rc = memory_stats.main(["--store", str(tmp_path / "nope")])
    assert rc == 0
    assert "no log entries" in capsys.readouterr().err


def test_json_output_is_machine_readable(logged, capsys):
    memory_stats.main(["--store", str(logged), "--json"])
    assert json.loads(capsys.readouterr().out)["rejects"] == 3


@pytest.fixture()
def sessions(tmp_path, monkeypatch):
    """Three sessions, told apart by the id the harness exports to the shell the
    scripts run in: s1 searched and wrote, s2 searched three times and never
    wrote, s3 only wrote. The suite may itself run inside such a session, so
    the stamp the environment would add is switched off here."""
    monkeypatch.delenv(memory_lib.SESSION_ENV, raising=False)
    store = tmp_path / ".memory"
    store.mkdir()
    for event in [
        {"event": "search", "query": "pty", "hits": 1, "top": "a", "session": "s1"},
        {"event": "write", "slug": "a", "mode": "create", "chars": 400, "session": "s1"},
        {"event": "search", "query": "pty", "hits": 1, "top": "a", "session": "s2"},
        {"event": "search", "query": "ws", "hits": 0, "top": None, "session": "s2"},
        {"event": "search", "query": "id", "hits": 1, "top": "a", "session": "s2"},
        {"event": "write", "slug": "b", "mode": "create", "chars": 500, "session": "s3"},
        {"event": "search", "query": "no session", "hits": 0, "top": None},
    ]:
        memory_lib.log_event(store, event.pop("event"), **event)
    return store


def test_sessions_that_searched_and_never_wrote_are_counted(sessions):
    """The write side's number, with no hook to collect it: a session that read
    the memory and left nothing behind. Events without a session id are not a
    session — another harness, or an older log."""
    s = memory_stats.summarise(memory_stats.read_log(sessions, None))
    assert s["sessions"] == 3
    assert s["sessions_unrecorded"] == 1
    assert s["writes_per_session"] == round(2 / 3, 3)


def test_sessions_are_printed(sessions, capsys):
    memory_stats.main(["--store", str(sessions)])
    out = capsys.readouterr().out
    assert "sessions" in out and "never wrote" in out
