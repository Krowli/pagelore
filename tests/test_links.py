"""`[[slug]]` cross-links: parsed by `lib.links`, warned about (not refused) when
dangling by `lore write`, and surfaced as backlinks by `lore show`.

Warning, not refusal, because an agent legitimately writes page A linking to
page B before B exists — the two pages often come out of the same
investigation, in whichever order the agent gets to them.
"""
import pytest

from pagelore import lib, show
from pagelore import write as memory_write

LONG = ("The reap loop waits on the child before closing the master fd, so a child "
        "that ignores SIGTERM keeps the fd open and waitpid never returns. " * 3)

# Real body text from this repo's own .memory/, so the parser is exercised
# against links an agent actually wrote, not just hand-built cases. Copied
# rather than read live: the store changes over time and a test must not.
REAL_BODY_WITH_LINK = """\
## The Windows loss on 2026-09-26, found by tracing rather than by tuning

2. The holder exited, and its lock should have been taken over at once. It was not:
   `_process_alive` returned *alive* for a process that no longer exists (see
   [[windows-liveness-probe-kills]]).
"""

REAL_BODY_WITH_SUPERSEDED_LINK = """\
## Amendment 2026-08-17: there is an index now

The line above saying "no server, no index on disk" was true when it was written
and is no longer. It changes nothing about the choice recorded here, and it was
taken on speed alone, after the two lexical rankers measured statistically
identical. See [[fts5-index-is-a-cache]].
"""


def test_links_finds_a_plain_target():
    assert lib.links("See [[some-other-page]] for the fix.") == ["some-other-page"]


def test_links_finds_a_target_with_anchor_text():
    assert lib.links("See [[some-other-page|the fix]] for detail.") == ["some-other-page"]


def test_links_strips_surrounding_whitespace_in_the_target():
    assert lib.links("See [[ some-other-page ]] for the fix.") == ["some-other-page"]


def test_links_ignores_a_link_inside_a_fenced_code_block():
    body = "before\n```\nsee [[fenced-target]] here\n```\nafter [[real-target]]\n"
    assert lib.links(body) == ["real-target"]


def test_links_ignores_a_link_inside_a_tilde_fence():
    body = "~~~~\n[[fenced-target]]\n~~~~\n[[real-target]]\n"
    assert lib.links(body) == ["real-target"]


def test_links_ignores_a_link_inside_an_inline_code_span():
    body = "quoting a literal `[[not-a-link]]` in prose, but [[real-target]] is one."
    assert lib.links(body) == ["real-target"]


def test_links_handles_a_multi_backtick_inline_span_containing_a_backtick():
    body = "the span `` `[[not-a-link]]` `` has a literal backtick, [[real-target]] does not"
    assert lib.links(body) == ["real-target"]


def test_links_on_real_page_body_with_a_link_inside_a_code_span():
    assert lib.links(REAL_BODY_WITH_LINK) == ["windows-liveness-probe-kills"]


def test_links_on_real_page_body_with_a_prose_link():
    assert lib.links(REAL_BODY_WITH_SUPERSEDED_LINK) == ["fts5-index-is-a-cache"]


def test_links_returns_duplicates_in_appearance_order():
    body = "[[a]] and again [[b]] and once more [[a]]"
    assert lib.links(body) == ["a", "b", "a"]


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.ts").write_text("export {}")
    (tmp_path / ".memory").mkdir()
    return tmp_path


def run_write(repo, *args, body=LONG):
    argv = ["--store", str(repo / ".memory")]
    if body is not None:
        argv += ["--body", body]
    return memory_write.main([*argv, *args])


def ok_args(slug="pty-hangs-on-exit"):
    return ["--slug", slug, "--title", "PTY hangs on exit", "--kind", "bug",
            "--source", "src/real.ts"]


def test_a_dangling_link_warns_but_the_page_is_still_written(repo, capsys):
    body = LONG + "\n\nSee [[some-page-that-does-not-exist]] for background."
    rc = run_write(repo, *ok_args("links-a"), body=body)
    assert rc == 0
    err = capsys.readouterr().err
    assert ("⚠ [[some-page-that-does-not-exist]] names no page in this store "
            "— write it, or fix the slug") in err
    assert (repo / ".memory" / "links-a.md").is_file()


def test_a_link_to_a_page_that_exists_does_not_warn(repo, capsys):
    assert run_write(repo, *ok_args("links-target")) == 0
    capsys.readouterr()
    body = LONG + "\n\nSee [[links-target]] for background."
    rc = run_write(repo, *ok_args("links-b"), body=body)
    assert rc == 0
    assert "names no page" not in capsys.readouterr().err


def test_a_self_link_is_not_dangling_even_on_first_write(repo, capsys):
    """The page being created cannot already exist on disk when the check
    would otherwise run, so a self-link must be special-cased, not just
    checked against the filesystem."""
    body = LONG + "\n\nSee [[links-self]] for the running total."
    rc = run_write(repo, *ok_args("links-self"), body=body)
    assert rc == 0
    assert "names no page" not in capsys.readouterr().err


def test_a_dangling_link_is_reported_once_per_distinct_target(repo, capsys):
    body = LONG + "\n\n[[missing-one]] and again [[missing-one]] and [[missing-two]]"
    rc = run_write(repo, *ok_args("links-c"), body=body)
    assert rc == 0
    err = capsys.readouterr().err
    assert err.count("[[missing-one]] names no page") == 1
    assert "[[missing-two]] names no page" in err


def test_a_link_escaping_the_store_with_a_real_file_there_still_warns(repo, capsys):
    """`[[../outside]]` must never be resolved as `<store>/../outside.md` on
    disk — a file sitting there by coincidence (or by an attacker's design)
    must not be read as "the page exists". `../outside` is not a valid slug,
    so it is reported dangling without the filesystem ever being touched."""
    (repo / "OUTSIDE.md").write_text("not a page of this store")
    body = LONG + "\n\nSee [[../OUTSIDE]] for background."
    rc = run_write(repo, *ok_args("links-escape"), body=body)
    assert rc == 0
    assert "[[../OUTSIDE]] names no page" in capsys.readouterr().err


def test_an_absolute_link_target_warns_rather_than_checking_the_real_filesystem(repo, capsys):
    body = LONG + "\n\nSee [[/etc/hosts]] for background."
    rc = run_write(repo, *ok_args("links-absolute"), body=body)
    assert rc == 0
    assert "[[/etc/hosts]] names no page" in capsys.readouterr().err


def test_a_link_to_a_page_symlinked_out_of_the_store_still_warns(repo, capsys):
    """A slug that resolves to a symlink pointing outside the store is not a
    page of this store (same containment rule search and --supersedes use),
    so it must still warn rather than being treated as present."""
    secret = repo / ".env"
    secret.write_text("AWS_SECRET_ACCESS_KEY=hunter2\n")
    (repo / ".memory" / "escaped-page.md").symlink_to(secret)
    body = LONG + "\n\nSee [[escaped-page]] for background."
    rc = run_write(repo, *ok_args("links-symlink"), body=body)
    assert rc == 0
    assert "[[escaped-page]] names no page" in capsys.readouterr().err


def test_dangling_link_warning_is_logged_with_the_shared_warnings_field(repo):
    body = LONG + "\n\nSee [[nope]] for background."
    assert run_write(repo, *ok_args("links-d"), body=body) == 0
    from pagelore import stats as memory_stats
    records = memory_stats.read_log(repo / ".memory", None)
    entry = [r for r in records if r.get("event") == "write"][-1]
    assert "dangling_link" in entry["warnings"]


def test_show_prints_who_links_to_this_page(repo, capsys):
    memory_write.write_page(
        repo / ".memory", "target-page", "Target page", "bug", ["src/real.ts"],
        "## Cause\n\n" + LONG)
    memory_write.write_page(
        repo / ".memory", "linker-a", "Linker A", "bug", ["src/real.ts"],
        "## Cause\n\n" + LONG + "\n\nSee [[target-page]].")
    memory_write.write_page(
        repo / ".memory", "linker-b", "Linker B", "bug", ["src/real.ts"],
        "## Cause\n\n" + LONG + "\n\nAlso see [[target-page]].")
    capsys.readouterr()

    assert show.main(["target-page", "--store", str(repo / ".memory")]) == 0
    captured = capsys.readouterr()
    assert "linked from: linker-a, linker-b" in captured.err
    # stdout is still exactly the file on disk.
    assert captured.out == (repo / ".memory" / "target-page.md").read_text(encoding="utf-8")


def test_show_prints_nothing_extra_when_no_page_links_here(repo, capsys):
    memory_write.write_page(
        repo / ".memory", "lonely-page", "Lonely page", "bug", ["src/real.ts"],
        "## Cause\n\n" + LONG)
    capsys.readouterr()
    assert show.main(["lonely-page", "--store", str(repo / ".memory")]) == 0
    assert "linked from" not in capsys.readouterr().err


def test_show_excludes_the_page_itself_from_its_own_backlinks(repo, capsys):
    memory_write.write_page(
        repo / ".memory", "self-linker", "Self linker", "bug", ["src/real.ts"],
        "## Cause\n\n" + LONG + "\n\nSee [[self-linker]] for the running total.")
    capsys.readouterr()
    assert show.main(["self-linker", "--store", str(repo / ".memory")]) == 0
    assert "linked from" not in capsys.readouterr().err


def test_fence_regex_lives_only_in_lib():
    """No second copy of the fence pattern: write.py imports lib's."""
    assert memory_write._FENCE is lib._FENCE
