"""Shared helpers: locating the store, parsing pages, recording what happened.
Stdlib only."""
from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

STORE_ENV = "PAGELORE_DIR"
# Every variable this program reads was called PROJECT_MEMORY_* before 0.6.0, when
# the product still had two names. The old spelling is read as a fallback, with a
# warning on stderr, for one minor release; 0.7.0 drops it. See `env`.
ENV_PREFIX = "PAGELORE_"
LEGACY_ENV_PREFIX = "PROJECT_MEMORY_"
_warned_env: set[str] = set()
STORE_DIRNAME = ".memory"
LOG_NAME = ".log.jsonl"
# One O_APPEND write is atomic against other processes on POSIX, and is not on
# Windows, where 17 of 200 concurrent lines went missing. This serialises the
# threads inside one process; O_APPEND still covers the cross-process case.
_LOG_LOCK = threading.Lock()
# Written by `lore init --store tracked`: the pages here are meant to be
# committed, so nothing should quietly add them to .gitignore behind the user.
TRACKED_MARKER = ".tracked"
# Claude Code exports the session id to the Bash tool, which is where the scripts
# run; stamped into every log line, it lets memory_stats count the sessions that
# searched and never wrote. Not in the documented environment, so its absence is
# fine — the record simply carries no session.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

LOCK_STALE_SECONDS = 30.0
# How long to wait for a lock whose owner is still alive. A dead owner is handled
# separately and at once by `_owner_is_gone`, so this number only has to cover a
# live holder that is slow — and it was tuned against a fast POSIX filesystem. Twelve
# writers onto one slug, which is what subagent fan-out produces, ran past ten
# seconds on a Windows runner and the last one proceeded unlocked and lost a section.
# Waiting longer costs nothing when there is no contention.
LOCK_TIMEOUT_SECONDS = 60.0
# Windows refuses to replace a file another process has open; POSIX never does.
REPLACE_TIMEOUT_SECONDS = 5.0


class StoreUnavailable(Exception):
    """The store path exists but cannot be used as a directory.

    `lore init --store home` makes the store a symlink; if its target is gone,
    `Path.exists()` follows the link and reports False while `mkdir` fails. That
    used to surface as a raw FileExistsError traceback from the write path, which
    is the one shape a refusal must never take — the agent gets no FIX: line and
    no way to tell a broken store from a bad page.
    """


def env(name: str) -> str | None:
    """`$PAGELORE_<X>`, else the pre-0.6.0 `$PROJECT_MEMORY_<X>`, else None.

    The old name still works for this minor release so that a shell profile or an
    MCP config written for 0.5 does not silently stop applying on upgrade. It says so
    once per process, on stderr: stdout is `--json` output or an MCP stream, and a
    line there would corrupt it.
    """
    value = os.environ.get(name)
    if value:
        return value
    old = LEGACY_ENV_PREFIX + name[len(ENV_PREFIX):]
    value = os.environ.get(old)
    if value and old not in _warned_env:
        _warned_env.add(old)
        print(f"pagelore: {old} is deprecated, use {name}; the old name stops working "
              "in 0.7.0", file=sys.stderr)
    return value or None


def find_store(start: Path | None = None) -> Path:
    """Locate the memory store: $PAGELORE_DIR, else nearest .memory/ upward."""
    override = env(STORE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / STORE_DIRNAME).is_dir():
            return candidate / STORE_DIRNAME
    return cur / STORE_DIRNAME


def store_problem(store: Path) -> str | None:
    """Why this path cannot hold a store, or None if it can."""
    if store.is_symlink() and not store.exists():
        return (f"{store} is a symlink whose target is missing "
                f"({os.readlink(store)})")
    if store.exists() and not store.is_dir():
        return f"{store} exists and is not a directory"
    return None


@dataclass
class Page:
    slug: str
    title: str
    body: str
    path: Path
    meta: dict = field(default_factory=dict)

    @property
    def superseded_by(self) -> str | None:
        value = self.meta.get("superseded_by")
        return str(value) if value else None

    @property
    def updated(self) -> str:
        return str(self.meta.get("updated") or self.meta.get("created") or "")

# Below this, a page is restating what the source file already says. Tuned to
# the stub population it is meant to exclude (bodies around 139 characters).
# The writer refuses a page under it; the reader skips one, because a page can
# arrive around the writer — by hand, from another tool, from an agent whose
# harness cannot deny a Write — and the check has to hold wherever search runs.
MIN_BODY = 200


def too_thin(page: Page) -> bool:
    return len(page.body.strip()) < MIN_BODY


_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _unquote(value: str) -> str:
    """Strip one matched pair of surrounding quotes, and only a matched pair.

    `.strip("\"'")` ate a real character: a title ending in a quote came back one
    character shorter on every rewrite, losing a little more each time.
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value

# Keys whose value is a list even when a page carries it as a bare scalar.
# `sources: src/real.ts` parsed to a string, and set() over a string yields one
# source per character — which destroyed the page's only anchor to the code.
LIST_KEYS = ("sources", "supersedes")


def read_text(path: Path) -> str:
    """Read a page tolerantly.

    One byte of Windows-1251 pasted into one page used to end every search in the
    project with a UnicodeDecodeError, while writes to other slugs kept
    succeeding — the store grew while retrieval was dead. A replacement character
    in one page costs that page some recall; a traceback costs all of them.
    """
    deadline = time.monotonic() + REPLACE_TIMEOUT_SECONDS
    while True:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            # Windows only: while a writer is swapping the file into place a reader
            # gets a sharing violation. POSIX readers keep reading the old inode and
            # never see this. Without the retry a search silently drops the page
            # that was being written — degraded rather than wrong, but avoidable.
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)


def parse_page(path: Path) -> Page:
    """Parse a memory page. Tolerates both inline `sources: [a, b]` and block lists."""
    raw = read_text(path)
    meta: dict = {}
    body = raw
    m = _FM.match(raw)
    if m:
        body = raw[m.end():]
        key = None
        for line in m.group(1).splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if re.match(r"^\s*-\s+", line) and key:
                meta.setdefault(key, [])
                if isinstance(meta[key], list):
                    meta[key].append(_unquote(line.split("-", 1)[1]))
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                meta[key] = [_unquote(v) for v in val[1:-1].split(",") if v.strip()]
            elif val:
                meta[key] = _unquote(val)
            else:
                meta[key] = []
    for key in LIST_KEYS:
        if isinstance(meta.get(key), str):
            meta[key] = [meta[key]]
    slug = str(meta.get("slug") or path.stem)
    title = str(meta.get("title") or slug.replace("-", " "))
    return Page(slug=slug, title=title, body=body, path=path, meta=meta)


def is_page(path: Path, root: Path) -> bool:
    """Whether this entry may be read or written as a page of `root`.

    Three separate ways a directory entry can be hostile, all seen in practice:

    - a symlink resolving outside the store. `ln -s ../.env .memory/env-notes.md`
      turned a search the agent runs on its own into an exfiltration primitive,
      ranking the secret and printing it to stdout. A symlink is also the one
      shape of this that git can carry, so it can arrive in a pull request.
    - something that is not a regular file at all: a directory named `notes.md`,
      a broken symlink, or a FIFO — which does not merely fail, it hangs every
      search forever with no timeout.
    - a file that cannot be read.

    A hard link is deliberately *not* covered: it is indistinguishable from an
    ordinary file by path, and git cannot carry one, so it needs local write
    access to the repository — at which point a page can simply be written.
    """
    try:
        if not path.is_file():
            return False
        if path.is_symlink() and root not in path.resolve().parents:
            return False
    except OSError:
        return False
    return True


def page_paths(store: Path) -> list[Path]:
    """The pages of a store: top-level `*.md`, and nothing that leaves it.

    Top-level only, because `rglob` kept an archived page indexed after the one
    archive gesture a human has (`mkdir archive; mv`) and returned two hits with
    the same slug — so the documented `cat .memory/<slug>.md` silently got the
    wrong one.
    """
    if not store.is_dir():
        return []
    root = store.resolve()
    return [p for p in sorted(store.glob("*.md")) if is_page(p, root)]


def load_pages(store: Path) -> list[Page]:
    out = []
    for path in page_paths(store):
        try:
            out.append(parse_page(path))
        except OSError:
            continue  # unreadable now; one bad entry must not end the search
    return out


# A fence is three OR MORE backticks or tildes. Matching exactly three was a real
# bug: quoting a memory page requires a ````-fence around a page that itself
# contains ```, and the first inner ``` then closed the outer fence, exposing a
# quoted `## ` line as a heading. CommonMark's rule is used for the close — same
# character, and at least as long as the opening run. Shared by write.py's
# split_sections and links() below: both walk a body line by line deciding
# what is inside a code fence, and a second copy of this regex drifting out of
# sync with the first would make the two disagree about it.
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

# [[target]] or [[target|anchor text]]. The target excludes "]" and "|" so a
# malformed or nested bracket does not eat the rest of the line.
_LINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")

# An inline code span: a run of one or more backticks, closed by a run of the
# same length. `(?<!`)` before the closing run and `(?!`)` after it reject a
# would-be close that is really part of a longer run — the standard trick for
# telling `` `a` `` (span closes after "a") from ``` ``a` ``` (the lone
# backtick inside is content, not a close, because it is not length 2).
_INLINE_CODE_RE = re.compile(r"(`+).*?(?<!`)\1(?!`)")


def links(body: str) -> list[str]:
    """Targets of `[[slug]]` / `[[slug|anchor text]]` links, in appearance order.

    Duplicates are kept — callers dedupe if they need to, since write.main's
    warning wants first-appearance order over distinct targets while show.py's
    backlink check only wants membership. A link inside a fenced code block or
    an inline code span is not a cross-reference, it is the literal text
    `[[...]]` being discussed, so both are excluded before matching: fences with
    the same open/close rule as split_sections, code spans by stripping them
    out of each line first.
    """
    out: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        match = _FENCE.match(line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        stripped = _INLINE_CODE_RE.sub("", line)
        out.extend(m.group(1).strip() for m in _LINK_RE.finditer(stripped))
    return out


def find_page(store: Path, slug: str) -> Page | None:
    """The page a search result named, or None.

    By slug rather than by filename: a page carries its slug in the frontmatter and
    a file renamed by hand keeps the old one, and the slug is what search prints.
    Goes through `page_paths` so the filters on what may be read apply here too.
    """
    for page in load_pages(store):
        if page.slug == slug:
            return page
    return None


def refuse_missing(store: Path, slug: str, cmd: str) -> int:
    """Say that no page has this slug, and what to run instead. Exit code 2.

    A `FIX:` line, because an agent that typed a slug from memory is one search
    away from the right one, and its loop already knows to follow that line.
    """
    print(f"no page {slug!r} in {store}", file=sys.stderr)
    print(f"FIX: {cmd} search {slug!r}", file=sys.stderr)
    return 2


def ensure_store(store: Path) -> None:
    """Create the store if it is missing, and make a brand-new one private.

    Installed globally, the skill meets projects it has never seen; the first
    write in each of them creates a store. Shielding it at creation is the only
    moment where nobody has to remember to do it — and the mistake it prevents
    (notes pushed to a remote) cannot be undone afterwards.

    Only creation triggers this. A store that already exists is left alone: if
    the line was removed, that was a decision.
    """
    problem = store_problem(store)
    if problem:
        raise StoreUnavailable(problem)
    if store.exists():
        return
    store.mkdir(parents=True, exist_ok=True)
    if (store / TRACKED_MARKER).exists():
        return
    try:
        gitignore = store.parent / ".gitignore"
        existing = read_text(gitignore) if gitignore.exists() else ""
        # `/.memory/` is the form GitHub's UI and many templates emit.
        if any(line.strip().strip("/") == store.name.strip("/")
               for line in existing.splitlines()):
            return
        prefix = "" if (not existing or existing.endswith("\n")) else "\n"
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}\n# pagelore: notes stay local\n{store.name}/\n")
    except OSError:
        # A read-only checkout should not stop the write; the pages still land.
        pass


def atomic_write(path: Path, text: str) -> None:
    """Replace a file's contents in one step.

    Rewriting in place truncates first, so a concurrent search could parse a
    half-written page and rank the fragment as the page's real content, and a
    crash in that window left the page permanently short with no backup.

    The scratch name carries the thread id as well as the pid. With the pid alone
    two threads in one process picked the same scratch file, and each deleted or
    replaced the other's: `os.replace` then raised FileNotFoundError on a file that
    had existed a moment earlier. One process per write is the shipped shape, so
    nothing hit this in production, but `write_page` is importable and the MCP probe
    calls it directly.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        # POSIX replaces a file no matter who has it open. Windows refuses with
        # WinError 5 while any reader holds a handle, and a search reading the
        # store is exactly that reader — so a concurrent search made a write fail
        # outright rather than merely wait.
        deadline = time.monotonic() + REPLACE_TIMEOUT_SECONDS
        while True:
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.01)
    except BaseException:
        tmp.unlink(missing_ok=True)  # no litter in the store on a failed write
        raise


def _windows_process_alive(pid: int, kernel32, last_error) -> bool | None:
    """The Windows half of `_process_alive`, with the API handed in so that the
    decision can be tested on a machine that is not Windows.

    It used to answer the "no such process" error with `True` — alive — which is
    the one answer that matters here inverted. A lock whose owner had exited and
    been reaped was then never taken over, every waiter sat out the full timeout
    and all of them wrote unlocked at once: sections lost, every command exiting 0.
    It went unnoticed because the test asked about a child whose `Popen` still held
    a handle, and a process somebody holds a handle to still opens — the exit-code
    branch answered, correctly, and the error branch never ran.
    """
    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5  # exists, and is not ours to open
    ERROR_INVALID_PARAMETER = 87  # no process with that id
    STILL_ACTIVE = 259
    import ctypes

    handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = last_error()
        if error == ERROR_INVALID_PARAMETER:
            return False
        if error == ERROR_ACCESS_DENIED:
            return True
        return None
    try:
        # A process that has exited still opens successfully while anyone holds a
        # handle to it, so the handle alone means nothing. The exit code does — and
        # 259 is the one value that cannot be distinguished from "running", which is
        # why it is reserved.
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(pid: int) -> bool | None:
    """Whether that process still exists. None when this platform cannot say.

    `os.kill(pid, 0)` is the POSIX idiom and is a liveness *probe* there. On
    Windows it is not: the documentation is explicit that any signal other than
    CTRL_C_EVENT and CTRL_BREAK_EVENT is delivered by calling TerminateProcess, so
    the "probe" kills the process it was asking about. Shipping that would have
    made every contended write terminate a sibling writer — CI caught it as a
    hang, which was the mild version of the symptom.
    """
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
            kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
            return _windows_process_alive(pid, kernel32, ctypes.get_last_error)
        except Exception:
            return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, and is not ours to signal
    except OSError:
        return None
    return True


def _owner_is_gone(lock: Path) -> bool:
    """Whether the process that took this lock no longer exists.

    The first version of this timed out after ten seconds and then unlinked
    whatever lock it found. That is worse than no lock at all: a single orphan
    file left by a killed writer stalled every other writer for the full timeout
    and then had them delete each other's *live* locks, which lost sections
    exactly the way the lock was introduced to prevent — measured at 2 to 4 of 10
    writers, all exiting 0.

    So staleness is decided by asking the operating system whether the owner is
    still alive, not by a clock. The mtime rule stays only as a fallback for a
    lock whose owner cannot be identified — an unparseable file, or one written
    on another machine on a shared filesystem.
    """
    try:
        raw = lock.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    try:
        pid = int(raw.split()[0])
    except (ValueError, IndexError):
        pid = None

    if pid is not None and raw.endswith(_boot_id()):
        if pid == os.getpid():
            return False
        alive = _process_alive(pid)
        if alive is not None:
            return not alive

    try:
        return (time.time() - lock.stat().st_mtime) > LOCK_STALE_SECONDS
    except OSError:
        return False


def _boot_id() -> str:
    """Identifies this host, so a PID written on another machine sharing the
    filesystem is never mistaken for a live local process. Deliberately not a
    boot timestamp: two processes must compute the same string, and any clock
    arithmetic drifts between them."""
    return platform.node() or "unknown-host"


class page_lock:
    """Serialise read-modify-write on one page across processes.

    A write parses the page, merges in memory and rewrites the whole file. Two
    agents on the same slug — ordinary with subagent fan-out — meant the second
    writer's whole section disappeared while both commands exited 0. Measured
    before this existed: concurrent writers lost up to 16 of 20 sections.

    Advisory: after LOCK_TIMEOUT_SECONDS the write proceeds without the lock
    rather than failing, because losing a section is bad but refusing to record
    anything at all is worse. It never removes a lock whose owner is alive.
    """

    def __init__(self, path: Path):
        self.lock = path.with_name(f".{path.name}.lock")
        self.fd: int | None = None
        # False when the timeout fired or the store could not be locked at all, so
        # the caller can tell an ordinary write from one that raced. Nothing here
        # refuses to write; the flag exists so the caller can check its own work.
        self.held = False

    def __enter__(self) -> page_lock:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                self.fd = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(self.fd, f"{os.getpid()} {_boot_id()}".encode())
                self.held = True
                return self
            except FileExistsError:
                if _owner_is_gone(self.lock):
                    try:
                        self.lock.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    # Proceed unlocked. Do NOT unlink: the holder is alive, and
                    # taking its lock away is what turned a stall into data loss.
                    return self
                time.sleep(0.02)
            except PermissionError:
                # Windows answers "access denied" rather than "exists" while the
                # lock is being deleted — a release in progress, which is contention,
                # not a store that cannot be locked. Treating it as the latter sent
                # the writer on unlocked in the middle of someone else's write.
                if not os.access(self.lock.parent, os.W_OK) or time.monotonic() > deadline:
                    return self
                time.sleep(0.02)
            except OSError:
                return self  # a store we cannot lock is still a store we can write

    def __exit__(self, *exc) -> None:
        if self.fd is None:
            return
        os.close(self.fd)
        self.fd = None
        # Windows refuses to delete a file another process has open, and a waiter
        # reading the owner's pid out of this lock is exactly that. A release that
        # gave up on the first refusal left the lock behind with a pid in it that
        # was about to exit — every writer behind it then depended on the liveness
        # probe to take it over. The read lasts microseconds, so wait it out, the
        # way `atomic_write` waits out a search holding the page.
        deadline = time.monotonic() + REPLACE_TIMEOUT_SECONDS
        while True:
            try:
                self.lock.unlink()
                return
            except PermissionError:
                if time.monotonic() > deadline:
                    return
                time.sleep(0.01)
            except OSError:
                return


def log_event(store: Path, event: str, *, create: bool = False, **fields) -> None:
    """Append one JSON line to the store's log. Never raises.

    Without this there is no way to answer how often the write gate fired and on
    what, except from memory — and a check whose result nobody collects is
    indistinguishable from no check. The log also captures the queries actually
    asked, which is the only honest basis for re-tuning ranking later.

    It holds real queries and slugs, so it is shielded from git inside the store
    rather than relying on the store's own mode.

    `create` is the write path's flag, and only the write path's. A refusal is
    often the very first thing that happens in a new project, so it has to be
    able to create the store it shields. A search must not: logging a miss used
    to mkdir a store and append three lines to the project's .gitignore on the
    first exploratory query in a repository that never opted in, which is a
    read-only operation dirtying a working tree.
    """
    try:
        if create:
            ensure_store(store)
        elif not store.is_dir():
            return
        ignore = store / ".gitignore"
        if not ignore.exists():
            with ignore.open("w", encoding="utf-8") as fh:
                fh.write(f"# holds every query and refusal; never commit it\n{LOG_NAME}\n")
        session = os.environ.get(SESSION_ENV)
        record = {"ts": _dt.datetime.now().isoformat(timespec="seconds"),
                  "event": event, **({"session": session} if session else {}), **fields}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        # One O_APPEND write() per line, so parallel writers cannot interleave
        # halves of two records into one unparseable line.
        with _LOG_LOCK:
            fd = os.open(store / LOG_NAME, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
    except Exception:
        # Telemetry must never be the reason a write or a search fails.
        pass
