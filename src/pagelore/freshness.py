"""Whether a page's `sources` moved on after the page did — from git, not disk.

A page's own `updated` field is day-granular and is written *before* the commit
that carries it exists, so it cannot answer "which came first, this page or that
source" against another file's own commit history. A file's mtime is worse: a
fresh clone or a CI checkout stamps every file with the checkout time, so every
page would read as stale on the first run after cloning. Git commit time is the
one clock both the page and its sources are stamped with, so it is the only one
that can be compared at all — page and source landing in the *same* commit read
as "fresh", not stale, because that is one clock reading, not two.

This only works if the surrounding directory is a real git work tree and the
repository can be asked at all. Without that there is no reliable way to decide
`gone` either — sources are cited relative to the project root, and the project
root is only known here because git named it. So the whole feature falls silent
together: no git reachable (not a repository, the binary is missing, the call
times out) means no markers at all, not a guess.

Stdlib only, and this module imports from `.lib` alone — never `.write` or
`.search` — so it stays a leaf: `search.py` needs this, and a leaf module cannot
import back into either of the modules that call it.
"""
from __future__ import annotations

import posixpath
import subprocess
import threading
import unicodedata
from pathlib import Path

from .lib import Page, resolve_source

GIT_TIMEOUT_SECONDS = 10


def _matchable(path: str) -> str:
    """A path, reduced to the form that decides whether it is the same file git
    named — not a value ever shown to anyone.

    `posixpath.normpath` so a source cited as `./src/a.py` (accepted by
    `write.validate`, which only checks that the target exists) is the same key
    as `src/a.py`, which is the spelling `--name-only` prints — the same
    normalisation `search._root_relative` applies for `--touching`, not imported
    here since `freshness` stays a leaf.

    `unicodedata.normalize("NFC", ...)` because this project has already been
    bitten once by an NFC/NFD mismatch on file *content* (a macOS NFD string was
    unfindable by an NFC query — `.memory/nfc-before-tokenising.md`) and the same
    two forms exist for a *path*. Measured directly for this fix: on this
    machine (`git config core.precomposeunicode` is `true`, the macOS default),
    git itself already precomposes a decomposed filename back to NFC before it
    is ever committed, so `git log --name-only` and an NFC-typed citation
    already matched with no help from this function. That setting is a
    per-install default, not a guarantee — a Linux checkout of a repository
    whose tree was written with `core.precomposeunicode=false`, or a source cited
    in the frontmatter in NFD because it was pasted from somewhere that is,
    would not have git's help — so the normalisation is kept as defence in
    depth even though no test in this repository's own environment reproduces a
    mismatch.
    """
    return unicodedata.normalize("NFC", posixpath.normpath(path))


def _inside_root(path: str) -> bool:
    """Whether a root-relative citation still names something inside the root
    after normalisation — not merely whether the string starts with `..`.

    `git log -- <pathspec>` exits 128 ("outside repository") the moment *any*
    one pathspec in the call resolves outside the worktree, and `last_commits`
    treats a non-zero exit as "git could not answer" and returns None for the
    *whole* call — so a single page citing `--source ../secrets.txt` or
    `--source /etc/hosts` (both accepted by `write.validate`, which only checks
    that the target exists on disk, not that it is inside the repo) used to
    blank `changed` for every page, not just its own. `drift` calls this to
    keep such a source out of the paths it hands to git; `gone` still checks it
    via `resolve_source`, which is unaffected.
    """
    norm = posixpath.normpath(path)
    return not posixpath.isabs(norm) and norm != ".." and not norm.startswith("../")


def last_commits(root: Path, paths: list[str]) -> dict[str, int] | None:
    """The committer time of the newest commit touching each of `paths`, or None
    if git could not answer at all (not a repository, no git binary, a timeout).

    Returned keyed by the exact strings in `paths`, whatever spelling the caller
    used — matching against what git prints back is internal, via `_matchable`.

    One `git log` call for every path at once, not one call per path: the cost of
    this feature is one subprocess per search, regardless of how many pages it
    touches. `--relative` is the fix for a store that lives in a subdirectory of a
    larger repository (a monorepo): `-C root` resolves the pathspecs after `--`
    against `root`, but without `--relative` the `--name-only` listing comes back
    relative to the repository's true top level, which can be an ancestor of
    `root` — so a source cited as `src/a.py` would never match the `apps/x/src/a.py`
    git actually printed. `--relative` makes that listing relative to `-C`'s
    directory too, the same root the pathspecs were already resolved against, so
    the two sides are directly comparable. Verified against `git help log` /
    `git help diff-options` (the `--relative[=<path>]` entry), not from memory.

    `-c core.quotePath=false` because git's default is to quote a non-ASCII byte
    in a path as a C-style octal escape (`"src/caf\303\251.py"`) in every text
    output, `--name-only` included — without this, a source or a page whose name
    is not plain ASCII never matches anything this module looks up, and `changed`
    silently never fires for it. Verified against `git help config`
    (`core.quotePath`), not from memory.

    `encoding="utf-8", errors="replace"` explicitly, rather than `text=True`
    alone: `text=True` with no `encoding` decodes the child's output in whatever
    `locale.getpreferredencoding()` says at import time — on a non-UTF-8 locale
    (`cp1252`, still the Windows default in many installs) a raw UTF-8 path byte
    that `core.quotePath=false` now lets through unescaped can raise
    `UnicodeDecodeError` while iterating `proc.stdout` below. That is a
    `ValueError`, which nothing here catches, so it would propagate straight out
    of this function and crash `lore search` / `lore show` outright instead of
    falling back to no markers. Git's own output is UTF-8 regardless of the
    caller's locale, so decoding as UTF-8 is always the right choice here;
    `errors="replace"` is the same tolerance `lib.read_text` already applies to a
    page file with a stray bad byte, for the same reason — one unreadable name
    should cost that one name, not the whole call.

    `%x00` is git's own escape for a NUL byte inside `--format`, spelled out as
    those literal characters — an actual NUL cannot survive as part of an argv
    string. It cannot appear in a real commit message or filename, so a NUL at
    the start of a line can never be mistaken for content — it always marks the
    start of the next commit's formatted line, never a filename.

    History comes back newest-first, so once every path in `paths` has a
    timestamp nothing further back in the log could still change the answer —
    `subprocess.Popen` is used instead of `subprocess.run` so this function can
    read `git log`'s stdout one line at a time and `terminate()` the process the
    moment `remaining` empties out, rather than paying for git to walk (and print)
    the rest of a history the answer no longer depends on. A path never committed
    still needs the full walk — there is no earlier point at which "never" can be
    known — so that case pays the old cost, same as before.
    """
    if not paths:
        return {}

    # Two different callers can cite the same file under different spellings
    # (`src/a.py` and `./src/a.py` both normalise to one key) — every original
    # spelling that shares a key has to get the timestamp, not just whichever
    # one happened to be recorded last, or the other page's `changed` never
    # fires for it.
    by_match: dict[str, list[str]] = {}
    for p in paths:
        by_match.setdefault(_matchable(p), []).append(p)
    remaining = set(by_match)
    out: dict[str, int] = {}

    try:
        proc = subprocess.Popen(
            ["git", "-c", "core.quotePath=false", "-C", str(root), "log", "--relative",
             "--format=%x00%ct", "--name-only", "--", *paths],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", errors="replace")
    except OSError:
        return None

    # A Timer, not the `timeout=` keyword `subprocess.run` offered: that keyword
    # belongs to a call that blocks until the child exits, and this call must not
    # block that long when the read loop below may already be done with `proc`
    # well before then. The timer runs on its own thread and kills `proc` out from
    # under the loop, which then simply sees end of file, the same as if git had
    # exited on its own — `terminate`/`kill` only (no signals), so this works on
    # Windows too.
    timed_out = threading.Event()

    def _kill_on_timeout() -> None:
        timed_out.set()
        proc.kill()  # matches what subprocess.run itself did on a TimeoutExpired

    timer = threading.Timer(GIT_TIMEOUT_SECONDS, _kill_on_timeout)
    timer.start()
    found_all = False
    try:
        current_ts: int | None = None
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line[:1] == "\0":
                # The whole of a commit's formatted line is `%x00%ct` — nothing
                # else — so a leading NUL always starts a new commit and never a
                # filename.
                try:
                    current_ts = int(line[1:])
                except ValueError:
                    current_ts = None  # defensive; git's own output is well-formed
                continue
            if not line or current_ts is None:
                continue  # the blank separator line, or a name before any commit
            key = _matchable(line)
            if key in remaining:
                for spelling in by_match[key]:
                    out[spelling] = current_ts
                remaining.discard(key)
                if not remaining:
                    # Every path already has an answer — let git go rather than
                    # pay for the rest of the walk.
                    found_all = True
                    proc.terminate()
                    break
    finally:
        timer.cancel()
        proc.stdout.close()
        proc.wait()  # reap the child either way — never leave a zombie behind

    if timed_out.is_set():
        return None
    if found_all:
        return out
    if proc.returncode != 0:
        return None  # not a repository, or none of this ever happened to commit
    return out


def drift(pages: list[Page], store: Path) -> dict[str, dict[str, list[str]]]:
    """slug -> {"changed": [...], "gone": [...]} for pages whose sources moved on.

    `root` for both git and `resolve_source` is `store.parent` throughout this
    project's convention (see `resolve_source`, `search._root_relative`): the
    store lives at `<root>/.memory` by default, but even when it does not
    (`$PAGELORE_DIR` elsewhere), sources are always cited relative to the
    project root, which is `store.parent`.

    `gone`: the source no longer resolves through `resolve_source` — deleted, or
    renamed without updating the page. Decided from the filesystem, not git, so
    it applies even to a page or source git has never committed; the one
    condition is that git itself answered, since a source's root-relative
    citation cannot be resolved without a reliable root.

    `changed`: the source's last commit is strictly newer than the *page file's*
    last commit — or, for a page never committed (the default gitignored store, a
    home store, a page not committed yet), than the page file's mtime. A source
    with no commit of its own (created but never committed) is left out of
    `changed`: it has no commit time to compare. Uncommitted edits to an already-committed
    source do not move its commit time at all, so they are silently ignored,
    which is the intended behaviour: a page should not flap between marked and
    unmarked while someone is mid-edit.
    """
    root = store.parent
    paths: set[str] = set()
    page_rel: dict[str, str] = {}
    for page in pages:
        # A page outside the root (a home store reached through a symlink) has no
        # commit to look up, but its sources still do.
        try:
            rel = page.path.resolve().relative_to(root.resolve()).as_posix()
            page_rel[page.slug] = rel
            paths.add(rel)
        except (ValueError, OSError):
            pass
        for s in (page.meta.get("sources") or []):
            s = str(s)
            if _inside_root(s):
                paths.add(s)

    commits = last_commits(root, sorted(paths))
    if commits is None:
        return {}

    out: dict[str, dict[str, list[str]]] = {}
    for page in pages:
        page_ts = commits.get(page_rel.get(page.slug, ""))
        if page_ts is None:
            # Never committed — the default gitignored store, a home store, a page
            # not committed yet. A clone never creates such a file, so its mtime is
            # the time it was last written, not a checkout time.
            try:
                page_ts = int(page.path.stat().st_mtime)
            except OSError:
                page_ts = None
        changed: list[str] = []
        gone: list[str] = []
        for source in page.meta.get("sources") or []:
            source = str(source)
            if resolve_source(source, store) is None:
                gone.append(source)
                continue
            source_ts = commits.get(source)
            if page_ts is not None and source_ts is not None and source_ts > page_ts:
                changed.append(source)
        if changed or gone:
            out[page.slug] = {"changed": changed, "gone": gone}
    return out
