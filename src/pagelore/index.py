"""A persistent SQLite FTS5 index over the store — a cache the search may ignore.

The pages are the memory; this is only a way to find them faster. Every function
here returns `None` rather than raising, and `memory_search` falls back to reading
the markdown directly. That rule is not defensive style, it is the design: a
store on a read-only checkout, on a network home, owned by another user, or being
rebuilt by a sibling process must still answer, slower.

Why the shape is what it is — each of these was measured before it was written:

- **No WAL.** WAL cannot be read from a read-only database and does not work on a
  network filesystem, which is exactly what `lore init --store home` invites
  (an NFS or iCloud home directory). The default rollback journal reads fine in a
  0555 directory. WAL would also buy nothing: every process here is a writer.
- **The index lives outside the store.** In `tracked` mode anything inside gets
  committed, and a store created before this feature existed would never receive
  a new `.gitignore` line. It is keyed by a hash of the store's *resolved* path,
  so the `home` symlink and its target share one index.
- **Freshness is `(mtime_ns, size, ino, ctime_ns)` compared for equality.** Not an
  ordering: a clock that steps backwards makes a page look older, and "newer than
  the index" then reads stale content as fresh. Not `(mtime, size)` alone: `tar
  -xp`, `rsync -a` and `cp -p` restore mtimes, and only `ino`/`ctime` catch an
  equal-sized rewrite underneath them.
- **Rebuild whole, never repair in place.** A repair perpetuates any change it
  missed; a rebuild self-heals on the next mismatch. It is written to a temporary
  file and moved into place, so a reader never sees a half-built index.
- **One builder, elected without waiting.** With subagent fan-out, twenty searches
  hitting a cold index gave eleven `database is locked` failures. The winner of a
  non-blocking lock rebuilds; everyone else queries what is already there, and
  falls back to reading the markdown when the index does not yet cover the store.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from .lib import _boot_id, _owner_is_gone, env, page_paths

# Bumped when the on-disk shape changes. A mismatch rebuilds.
SCHEMA_VERSION = 1

# Bumped whenever `memory_search.tokenize` changes. The index stores its output,
# so a silent change to tokenisation would otherwise leave a store whose queries
# are tokenised one way and whose index was built another — zero recall, no error.
TOKENIZER_VERSION = 1

DISABLE_ENV = "PAGELORE_NO_FTS5"
BUILD_LOCK = ".index.lock"
# A builder that dies without releasing must not freeze the index forever. The
# liveness check covers a killed process; this covers a hung one.
BUILD_LOCK_CEILING = 120.0
# Below this share of the store, the index is treated as not yet usable and the
# caller reads the markdown instead — a half-built index answering with a third of
# the corpus is a silent wrong answer, which is worse than being slow.
MIN_COVERAGE = 0.9


def fts5_available() -> bool:
    """Whether this interpreter can use FTS5 at all.

    Deliberately not cached to disk: a cached "yes" survives a Python upgrade that
    drops FTS5, and a cached "no" survives one that adds it. Measured at 0.1-2 ms,
    which is under 3% of one invocation.

    `import sqlite3` lives here rather than at module scope on purpose — Debian's
    `python3-minimal` ships no `sqlite3` module at all, and a top-level import
    would turn a working search into a traceback on every search.
    """
    if env(DISABLE_ENV):
        return False
    try:
        import sqlite3
    except ImportError:
        return False
    try:
        conn = sqlite3.connect(":memory:")
    except Exception:
        return False
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except Exception:
        return False
    finally:
        conn.close()


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "pagelore"


def index_path(store: Path) -> Path:
    """Outside the store, keyed by its resolved path so a symlinked store and its
    target share one index."""
    try:
        key = str(store.resolve())
    except OSError:
        key = str(store)
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest()
    return cache_root() / f"{digest}.db"


def identity(store: Path) -> dict[str, tuple[int, int, int, int]]:
    """The fingerprint of the store as it is on disk right now.

    Built from `page_paths`, not a fresh glob, so the security filter is inherited:
    a symlink pointing out of the store is neither indexed nor able to force a
    permanent rebuild.
    """
    out: dict[str, tuple[int, int, int, int]] = {}
    for path in page_paths(store):
        try:
            st = path.stat()
        except OSError:
            continue
        out[path.name] = (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns)
    return out


def digest(fingerprint: dict[str, tuple[int, int, int, int]]) -> str:
    """One short string standing for the whole store.

    The index stored the fingerprint itself, which meant parsing a JSON object with
    one entry per page on every single search — 5000 pages made a warm search cost
    a second, most of it spent re-reading a structure only ever used for an
    equality test. Nothing needs to know *which* page changed, because the response
    to any change is a whole rebuild.
    """
    blob = "\n".join(f"{name}:{','.join(map(str, value))}"
                      for name, value in sorted(fingerprint.items()))
    return hashlib.blake2b(blob.encode("utf-8"), digest_size=16).hexdigest()


class _Builder:
    """Non-blocking election. The loser does not wait; it queries what exists."""

    def __init__(self, store: Path):
        self.lock = store / BUILD_LOCK
        self.fd: int | None = None
        self.won = False

    def __enter__(self) -> _Builder:
        try:
            self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(self.fd, f"{os.getpid()} {_boot_id()}".encode())
            self.won = True
        except FileExistsError:
            stale = _owner_is_gone(self.lock)
            if not stale:
                try:
                    stale = (time.time() - self.lock.stat().st_mtime) > BUILD_LOCK_CEILING
                except OSError:
                    stale = False
            if stale:
                try:
                    self.lock.unlink()
                except OSError:
                    pass
        except OSError:
            # Cannot create a lock here at all — a read-only store. Not the same
            # as "someone else is building", and it must not be reported as such.
            pass
        return self

    def __exit__(self, *exc) -> None:
        if self.fd is not None:
            os.close(self.fd)
            try:
                self.lock.unlink()
            except OSError:
                pass


def _connect(path: Path, *, read_only: bool):
    import sqlite3

    if read_only:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
    return sqlite3.connect(path, timeout=5.0)


def _read_meta(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {k: v for k, v in rows}


def _is_fresh(conn, fingerprint: dict) -> bool:
    meta = _read_meta(conn)
    if int(meta.get("schema_version", -1)) != SCHEMA_VERSION:
        return False
    if int(meta.get("tokenizer_version", -1)) != TOKENIZER_VERSION:
        return False
    return meta.get("identity") == digest(fingerprint)


def rebuild(store: Path, path: Path, tokenize, parse_page) -> bool:
    """Write a complete index to a temporary file and move it into place."""
    import sqlite3

    stamp = identity(store)  # stat BEFORE reading, or a page changed mid-build is
    pages = []              # recorded as current and pinned stale forever
    for page_path in page_paths(store):
        if page_path.name not in stamp:
            continue
        try:
            pages.append(parse_page(page_path))
        except OSError:
            stamp.pop(page_path.name, None)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.unlink(missing_ok=True)
        conn = sqlite3.connect(tmp)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE pages USING fts5(slug UNINDEXED, title, body, "
                "tokenize=\"unicode61 remove_diacritics 0 tokenchars '_'\")")
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            conn.executemany(
                "INSERT INTO pages (slug, title, body) VALUES (?, ?, ?)",
                [(p.slug,
                  " ".join(tokenize(f"{p.title} {p.slug}")),
                  " ".join(tokenize(p.body))) for p in pages])
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [("schema_version", str(SCHEMA_VERSION)),
                 ("tokenizer_version", str(TOKENIZER_VERSION)),
                 ("pages", str(len(pages))),
                 ("identity", digest(stamp))])
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp, path)
        return True
    except (sqlite3.Error, OSError):
        try:
            tmp.unlink(missing_ok=True)
        except (OSError, NameError):
            pass
        return False


def lookup(query: str, store: Path, limit: int, tokenize) -> list[tuple[float, str]] | None:
    """Slugs and scores from the index, or None to say "read the markdown".

    A higher score is better here, matching the in-process ranker; SQLite's
    `bm25()` returns the opposite sign, which is negated below.

    The weights are positional over EVERY column, `slug` included. Passing two
    weights for a three-column table silently gave the title weight to the
    unindexed slug and left the title at the default 1.0 — the title weighting,
    the single most valuable parameter in the ranker, was quietly absent. The
    regression test for it caught this.
    """
    if not fts5_available():
        return None
    import sqlite3

    path = index_path(store)
    on_disk = identity(store)
    if not on_disk:
        return None

    try:
        fresh = False
        if path.exists():
            try:
                conn = _connect(path, read_only=True)
                try:
                    fresh = _is_fresh(conn, on_disk)
                finally:
                    conn.close()
            except (sqlite3.Error, OSError):
                fresh = False

        if not fresh:
            with _Builder(store) as builder:
                if builder.won:
                    fresh = rebuild(store, path, tokenize, _page_parser())
            if not fresh and not path.exists():
                return None  # nothing to query and someone else is building

        conn = _connect(path, read_only=True)
        try:
            meta = _read_meta(conn)
            if int(meta.get("schema_version", -1)) != SCHEMA_VERSION:
                return None
            indexed = int(meta.get("pages", 0))
            if indexed < len(on_disk) * MIN_COVERAGE:
                # A stale or half-built index would answer from part of the store.
                return None
            terms = set(tokenize(query))
            if not terms:
                return []
            expr = " OR ".join(f'"{t}"' for t in terms)
            rows = conn.execute(
                "SELECT slug, -bm25(pages, 0.0, 5.0, 1.0) FROM pages "
                "WHERE pages MATCH ? ORDER BY 2 DESC LIMIT ?",
                (expr, limit)).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return None

    return [(float(score), slug) for slug, score in rows]


def _page_parser():
    from .lib import parse_page
    return parse_page


def forget(store: Path) -> None:
    """Drop the cached index for a store. Only used by tests and by a doctor path;
    a stale index heals itself, so nothing in normal operation needs this."""
    try:
        index_path(store).unlink(missing_ok=True)
    except OSError:
        pass
