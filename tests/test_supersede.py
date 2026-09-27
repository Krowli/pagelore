"""A reversed decision has to lose to the decision that reversed it.

This is the failure the README opens with — "agents confidently restate
decisions that were reversed months ago" — and until now the store had no way to
express it: both pages sat in the result list as peers, the older one often on
top, and the printed line carried no date.
"""
from pagelore import lib as memory_lib
from pagelore import search as memory_search
from pagelore import write as memory_write

LONG = ("Server-side sessions in Redis, not JWT: a denylist defeats statelessness, "
        "and the compliance rule gives us one second to revoke access. " * 3)


def write(store, slug, title, body, *, supersedes=None):
    argv = ["--store", str(store), "--slug", slug, "--title", title,
            "--kind", "decision", "--source", "a.ts", "--body", body]
    if supersedes:
        argv += ["--supersedes", supersedes]
    (store.parent / "a.ts").write_text("export {}")
    return memory_write.main(argv)


def test_superseding_stamps_both_pages(store):
    assert write(store, "auth-strategy", "Auth uses server-side sessions",
                 "## Decision\n\n" + LONG) == 0
    assert write(store, "auth-jwt-migration", "Auth moves to JWT",
                 "## Decision\n\n" + LONG, supersedes="auth-strategy") == 0

    old = memory_lib.parse_page(store / "auth-strategy.md")
    new = memory_lib.parse_page(store / "auth-jwt-migration.md")
    assert old.meta["status"] == "superseded"
    assert old.meta["superseded_by"] == "auth-jwt-migration"
    assert new.meta["supersedes"] == ["auth-strategy"]


REVERSAL_QUERY = "sessions jwt redis denylist"

FILLER = ("A denylist defeats statelessness and the compliance rule gives us one "
          "second to revoke access, which is why the earlier call went that way. " * 2)

# The old page names the option it rejected, repeatedly, because that is what a
# decision page does. The page that replaces it names only what it chose. So the
# obsolete page matches a query about the choice better than its replacement —
# which is exactly the case supersession has to survive.
OLD_BODY = ("## Decision\n\nWe keep sessions in Redis. JWT was considered and rejected: "
            "a JWT denylist defeats the statelessness that makes JWT attractive, and a "
            "JWT still needs a redis lookup on every request to be revocable. " + FILLER)
NEW_BODY = "## Decision\n\nWe move to JWT. " + FILLER


def a_reversed_pair(store, *, linked: bool):
    write(store, "auth-sessions", "Auth uses server-side sessions", OLD_BODY)
    write(store, "auth-jwt", "Auth moves to JWT", NEW_BODY,
          supersedes="auth-sessions" if linked else None)


def test_the_pair_is_a_real_inversion_when_nothing_links_them(store):
    """Guards the fixture, not the feature. An earlier version gave both pages the
    same title and body, so ordinary ranking plus the alphabetical tie-break
    happened to order them correctly — and the whole supersession mechanism could
    be deleted with the suite still green. Unlinked, the obsolete page must win."""
    a_reversed_pair(store, linked=False)
    hits = memory_search.search(REVERSAL_QUERY, store)
    assert [p.slug for _, p in hits] == ["auth-sessions", "auth-jwt"]


def test_the_replacement_outranks_what_it_replaced(store):
    """Same wording, same query — only the supersedes link is added."""
    a_reversed_pair(store, linked=True)
    hits = memory_search.search(REVERSAL_QUERY, store)
    assert [p.slug for _, p in hits] == ["auth-jwt", "auth-sessions"]


def test_a_replacement_is_never_the_hit_that_falls_off_the_end(store):
    """The pairwise correction runs before `k` truncates, or the page that answers
    the question is the one the agent never sees."""
    a_reversed_pair(store, linked=True)
    hits = memory_search.search(REVERSAL_QUERY, store, k=1)
    assert [p.slug for _, p in hits] == ["auth-jwt"]


def test_a_page_cannot_supersede_itself(store):
    write(store, "auth-sessions", "Auth uses server-side sessions",
          "## Decision\n\n" + LONG)
    assert write(store, "auth-sessions", "Auth uses server-side sessions",
                 "## Decision\n\nrevised. " + LONG, supersedes="auth-sessions") == 1
    assert "superseded" not in (store / "auth-sessions.md").read_text(encoding="utf-8")


def test_a_supersession_cycle_is_refused(store):
    """Every page in a cycle carries `status: superseded`, so the whole chain reads
    as obsolete and nothing in it is current."""
    write(store, "one", "Decision one", "## Decision\n\n" + LONG)
    write(store, "two", "Decision two", "## Decision\n\n" + LONG, supersedes="one")
    assert write(store, "one", "Decision one", "## Decision\n\nback again. " + LONG,
                 supersedes="two") == 1


def test_superseding_a_symlink_out_of_the_store_is_refused(store):
    """Stamping walks through the path, so this used to read the target and copy it
    into the store as a real page — re-opening the exfiltration hole that the read
    path had just been fixed to close, in the same changeset."""
    secret = store.parent / ".env"
    secret.write_text("AWS_SECRET_ACCESS_KEY=hunter2\n")
    (store / "env-notes.md").symlink_to(secret)
    rc = write(store, "new-decision", "A new decision", "## Decision\n\n" + LONG,
               supersedes="env-notes")
    assert rc == 1
    assert (store / "env-notes.md").is_symlink(), "the symlink was replaced by a real page"
    assert memory_search.search("secret access key hunter2", store) == []


def test_a_superseded_hit_says_so_in_the_result_line(store):
    write(store, "auth-strategy", "Auth strategy decision", "## Decision\n\n" + LONG)
    write(store, "auth-strategy-v2", "Auth strategy decision", "## Decision\n\n" + LONG,
          supersedes="auth-strategy")
    hits = memory_search.search("auth strategy decision", store)
    old = next(p for _, p in hits if p.slug == "auth-strategy")
    assert "superseded by auth-strategy-v2" in memory_search.format_hit(1.0, old)


def test_repeating_an_identical_supersede_leaves_the_old_page_untouched(store, monkeypatch):
    """`write_page` already skips the byte-identical rewrite of the *new* page, but
    `stamp_superseded` ran unconditionally on the *old* one — so an identical
    `--supersedes` re-run still rewrote it and bumped its `updated`, even though
    nothing about the supersession changed. Bytes alone would not catch this: a
    same-day rewrite stamps the same date and comes out byte-identical anyway, so
    the assertion patches `atomic_write` to prove the old page's file was never
    even touched the second time."""
    write(store, "auth-strategy", "Auth uses server-side sessions", "## Decision\n\n" + LONG)
    write(store, "auth-jwt-migration", "Auth moves to JWT", "## Decision\n\n" + LONG,
          supersedes="auth-strategy")

    old_path = store / "auth-strategy.md"
    before_bytes = old_path.read_bytes()

    written_paths = []
    real_atomic_write = memory_write.atomic_write

    def spy(path, text):
        written_paths.append(path)
        return real_atomic_write(path, text)
    monkeypatch.setattr(memory_write, "atomic_write", spy)

    assert write(store, "auth-jwt-migration", "Auth moves to JWT", "## Decision\n\n" + LONG,
                 supersedes="auth-strategy") == 0

    assert old_path not in written_paths
    assert old_path.read_bytes() == before_bytes


def test_superseding_a_page_that_does_not_exist_is_refused(store):
    rc = write(store, "auth-jwt", "Auth moves to JWT", "## Decision\n\n" + LONG,
               supersedes="never-existed")
    assert rc == 1
    assert not (store / "auth-jwt.md").exists()


def test_the_amendment_that_records_a_reversal_is_not_too_short(store):
    """MIN_BODY was applied to the increment rather than to the resulting page, so
    the cheapest and most valuable write in the system — "this was reversed in
    June, here is why" — was structurally forbidden."""
    write(store, "auth-strategy", "Auth strategy decision", "## Decision\n\n" + LONG)
    rc = write(store, "auth-strategy", "Auth strategy decision",
               "## Reversal 2026-06\n\nReversed: the vendor now revokes tokens for us.\n")
    assert rc == 0
    assert "Reversal 2026-06" in (store / "auth-strategy.md").read_text(encoding="utf-8")


def test_a_brand_new_page_still_has_to_carry_its_weight(store):
    assert write(store, "thin", "Thin page", "## Decision\n\ntoo short to keep\n") == 1
