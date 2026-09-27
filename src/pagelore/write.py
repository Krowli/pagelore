#!/usr/bin/env python3
"""Create or update a memory page.

Usage:
  lore write --slug SLUG --title TITLE --kind KIND
             --source PATH [--source PATH ...] --body TEXT|-
             [--supersedes SLUG] [--store DIR]

Re-running with the same slug replaces same-header sections and appends new
ones, so repeated calls are safe. What was replaced is printed, because a
replacement is destructive and the default store has no VCS behind it.

**A page that is not worth keeping is refused, not written.** The refusal exits
non-zero and names the next command, so the correction lands in the agent's own
loop instead of in a rules file it may not read. This is the whole design: in
the corpus this was built against, 104 of 495 pages were auto-generated stubs
whose bodies ran to about 139 characters, and they took the top two result slots
for real queries.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .cli import add_version
from .lib import (
    _FENCE,
    MIN_BODY,
    StoreUnavailable,
    atomic_write,
    ensure_store,
    find_store,
    is_page,
    links,
    log_event,
    page_lock,
    parse_page,
    read_text,
    resolve_source,
    store_problem,
)

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Every exact pattern below needs a left boundary: without one, `sk-` (and
# every other prefix) also matches mid-word, inside an ordinary kebab-case
# slug or wiki-link like `risk-assessment-of-the-renderer-pipeline` (contains
# "sk-assessment...") or `disk-image-based-backup-strategy` (contains
# "sk-image..."). A real credential is never preceded by another identifier
# character, so requiring that the character before the match is not
# alphanumeric/underscore/hyphen is exact, not a heuristic.
_BOUNDARY = r"(?<![A-Za-z0-9_-])"

# Exact credential formats. Each is refused outright — an exact match is cheap
# to get right and expensive to get wrong, so there is no threshold to tune.
# AWS, the classic GitHub token and the OpenAI key were checked against the
# legacy detector this replaces (secret_detector.rs:77-87). The rest were
# checked against an official source or gitleaks' own default ruleset, cited
# next to each pattern, and only formats that verified this way are included.
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key", re.compile(_BOUNDARY + r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(_BOUNDARY + r"gh[ps]_[A-Za-z0-9]{36}")),
    # GitHub fine-grained PAT. Verified against GitHub's own announcement:
    # https://github.blog/security/application-security/introducing-fine-grained-personal-access-tokens-for-github/
    # (`\bgithub_pat_[0-9A-Za-z_]{36,}\b`).
    ("github_fine_grained_pat", re.compile(_BOUNDARY + r"github_pat_[0-9A-Za-z_]{36,}")),
    # Anthropic API key. Verified against Anthropic's own docs, which show a
    # partial key as "sk-ant-api03-R2D...igAA":
    # https://platform.claude.com/docs/en/api/admin/api_keys/retrieve
    # Checked, and its match excluded, before the OpenAI pattern below so one
    # key produces one finding rather than two.
    ("anthropic_api_key", re.compile(_BOUNDARY + r"sk-ant-[A-Za-z0-9_\-]{32,}")),
    ("openai_api_key", re.compile(_BOUNDARY + r"sk-(?!ant-)[A-Za-z0-9_\-]{32,}")),
    # Slack bot/user/legacy-workspace tokens. Verified against gitleaks'
    # default ruleset: https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml
    ("slack_token", re.compile(
        _BOUNDARY + r"(?:xoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*"
        r"|xox[pe](?:-[0-9]{10,13}){3}-[a-zA-Z0-9-]{28,34}"
        r"|xox[ar]-(?:\d-)?[0-9a-zA-Z]{8,48})")),
    # PEM private key header. Verified against gitleaks' default ruleset (same
    # source as above); the opening delimiter alone is enough to flag it. No
    # left boundary: the delimiter itself starts with `-----`, so requiring a
    # non-hyphen character before it would be wrong, not safer.
    ("private_key_pem",
     re.compile(r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----")),
]

# A run of base64/hex-alphabet characters whose Shannon entropy is at or above
# this many bits per symbol reads as random, not written. The formula and the
# threshold are from the legacy detector this replaces (secret_detector.rs:111).
# A 40-char hex SHA never reaches it (at most log2(16) = 4.0 bits/char), so
# hashes and long snake_case identifiers pass through as plain text.
_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_\-]{40,}")
_ENTROPY_THRESHOLD = 4.5


def _shannon_entropy(s: str) -> float:
    length = len(s)
    counts = Counter(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def find_secrets(text: str) -> list[tuple[str, int]]:
    """Scan for exact credential formats, line by line.

    Takes the raw title/body as typed, not the page that results from merging
    with what is already on disk — old content already passed this check once,
    so re-scanning it on every amendment would cost time for no new safety.
    """
    found: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _SECRET_PATTERNS:
            if pattern.search(line) and (kind, line_no) not in seen:
                seen.add((kind, line_no))
                found.append((kind, line_no))
    return found


def find_high_entropy(text: str) -> list[int]:
    """Line numbers containing a long run that reads as random, not written.

    Non-fatal by design: unlike `find_secrets`, this has false positives on
    legitimate content (long tokens, encoded blobs), so it warns instead of
    refusing the write.
    """
    lines: list[int] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _ENTROPY_RE.finditer(line):
            if _shannon_entropy(match.group()) >= _ENTROPY_THRESHOLD:
                lines.append(line_no)
                break
    return lines


def locate_secrets(title: str, body: str) -> list[tuple[str, str]]:
    """`find_secrets`, but naming *where* in human terms.

    Title and body are scanned and numbered separately: `--body` is what the
    agent actually typed, so "line 3" has to mean the third line of the body
    text, not the third line of some internal concatenation with the title.
    """
    locations: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, _ in find_secrets(title):
        if (kind, "title") not in seen:
            seen.add((kind, "title"))
            locations.append((kind, "title"))
    for kind, line_no in find_secrets(body):
        where = f"body line {line_no}"
        if (kind, where) not in seen:
            seen.add((kind, where))
            locations.append((kind, where))
    return locations


def locate_high_entropy(title: str, body: str) -> list[str]:
    """`find_high_entropy`, but naming *where* in human terms. See `locate_secrets`."""
    locations: list[str] = []
    if find_high_entropy(title):
        locations.append("title")
    locations.extend(f"body line {n}" for n in find_high_entropy(body))
    return locations

# Kinds are deliberately few. The corpus that motivated this had a `rationale`
# kind produced by an automated scan; it became 23% of all pages and none of it
# was worth reading.
KINDS = ("decision", "bug", "concept", "howto")

# MIN_BODY lives in lib.py, shared with the reader. It is measured against
# the resulting page, not against one write: an amendment that records a
# reversal is the cheapest and most valuable write in the system, and a floor on
# the increment forbade exactly that.

# Frontmatter this script owns, in emission order. Everything else a page
# carries is preserved untouched — rebuilding from a fixed whitelist silently
# deleted any field a user or a later version added, which blocked the cheapest
# possible fix for superseded pages.
MANAGED_SCALARS = ("slug", "title", "kind", "created", "updated", "status", "superseded_by")
MANAGED_LISTS = ("supersedes", "sources")


def split_sections(body: str) -> list[tuple[str | None, str]]:
    """Split markdown into (header, chunk) pairs; leading text has header None.

    Fence-aware: a `## ` line inside a code fence is content, not a heading. The
    store's own subject is markdown pages, so a page that quotes a page is the
    normal case — and splitting inside the fence deleted the closing fence and
    everything after it on the next write.
    """
    out: list[tuple[str | None, str]] = []
    header: str | None = None
    buf: list[str] = []
    fence: str | None = None
    for line in body.splitlines(keepends=True):
        match = _FENCE.match(line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None and line.startswith("## "):
            out.append((header, "".join(buf)))
            header = line.strip()
            buf = [line]
            continue
        buf.append(line)
    out.append((header, "".join(buf)))
    return out


@dataclass
class MergeResult:
    body: str
    replaced: list[str] = field(default_factory=list)
    appended: list[str] = field(default_factory=list)


def merge(old_body: str, new_body: str) -> MergeResult:
    """Fold a new body into an existing page.

    Same header replaces in place — moving it to the end made a one-section
    amendment read as a whole-file rewrite in `git diff`. A new header is
    appended. Lead-in prose is the section with no header and follows the same
    rule: it used to be dropped whenever the page already had any, so a write
    with no `## ` heading at all vanished while the command exited 0.
    """
    old = split_sections(old_body)
    sections = split_sections(new_body)
    incoming_lead = "".join(c for h, c in sections if h is None).strip()

    # A dict comprehension here silently dropped all but the last of two sections
    # sharing a header, so a body with the same `## ` twice lost the first copy on
    # a merge while keeping both on a new page. Same-header chunks are joined.
    incoming: dict[str, str] = {}
    order: list[str] = []
    for header, chunk in sections:
        if header is None:
            continue
        if header in incoming:
            incoming[header] = incoming[header] + "\n\n" + chunk.strip()
        else:
            incoming[header] = chunk.strip()
            order.append(header)

    chunks: list[str] = []
    replaced: list[str] = []
    seen: set[str] = set()
    for header, chunk in old:
        if header is None:
            text = incoming_lead if incoming_lead else chunk.strip()
            if text:
                chunks.append(text)
            continue
        # Only the first stored occurrence is replaced. Replacing every one wrote
        # the same incoming text into the page twice.
        if header in incoming and header not in seen:
            replaced.append(header)
            chunks.append(incoming[header])
        else:
            chunks.append(chunk.strip())
        seen.add(header)

    if incoming_lead and not any(h is None for h, _ in old):
        chunks.insert(0, incoming_lead)

    appended = [h for h in order if h not in seen]
    chunks.extend(incoming[h] for h in appended)

    return MergeResult(body="\n\n".join(c for c in chunks if c) + "\n",
                       replaced=replaced, appended=appended)


def render_frontmatter(meta: dict) -> str:
    lines: list[str] = []
    for key in MANAGED_SCALARS:
        value = meta.get(key)
        if value in (None, "", []):
            continue
        lines.append(f'{key}: "{value}"' if key == "title" else f"{key}: {value}")
    for key in MANAGED_LISTS:
        values = meta.get(key) or []
        if values:
            lines.append(f"{key}:")
            lines.extend(f"  - {v}" for v in values)
    for key in sorted(set(meta) - set(MANAGED_SCALARS) - set(MANAGED_LISTS)):
        value = meta[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {v}" for v in value)
        elif value not in (None, ""):
            lines.append(f"{key}: {value}")
    return "---\n" + "\n".join(lines) + "\n---\n\n"


# Three, not more: each retry is a full read-merge-write, and the case it covers is
# already a writer that could not get a lock for a minute. Looping past that trades a
# possible lost section for a command that never returns.
UNLOCKED_RETRIES = 3

# Whether the last write_page() call found the candidate page byte-identical to
# what was already on disk and skipped the write. Module state like search.py's
# `last_path`/`last_touching`, so write_page's return type (and its ~15 call
# sites across tests and evals/run.py) stay a bare `Path`: the decision is made
# once, inside the lock, against the file read under that same lock — a second,
# unlocked before/after read in main() could disagree with it under a
# concurrent writer.
last_unchanged = False


def write_page(store: Path, slug: str, title: str, kind: str,
               sources: list[str], body: str,
               supersedes: list[str] | None = None) -> Path:
    global last_unchanged
    last_unchanged = False
    if not SLUG_RE.match(slug):
        raise ValueError(
            f"invalid slug {slug!r}: lowercase letters, digits and single hyphens only")
    ensure_store(store)
    path = store / f"{slug}.md"
    today = _dt.date.today().isoformat()
    wanted = [h for h, _ in split_sections(body) if h is not None]

    # The lock is advisory: after LOCK_TIMEOUT_SECONDS a writer proceeds without it,
    # because losing a section is bad and refusing to record anything is worse. That
    # leaves one window in which two writers can both be between their read and their
    # write, and a Windows runner with twelve writers on one slug found it — section
    # 00 vanished while every command exited 0, which is the exact failure the lock
    # exists to prevent. So an unlocked write now checks its own work and tries again.
    # A locked write is the normal path and pays nothing for this.
    for attempt in range(UNLOCKED_RETRIES):
        with page_lock(path) as lock:
            meta: dict = {}
            result = MergeResult(body=body)
            merged_sources, merged_supersedes = sources, supersedes
            existing_text: str | None = None
            if path.exists():
                # Tolerant read (replaces a bad byte, retries a Windows sharing
                # violation): a page with one non-UTF-8 byte in it must still be
                # rewritable, exactly as it was before this comparison existed.
                existing_text = read_text(path)
                existing = parse_page(path)
                meta = dict(existing.meta)
                result = merge(existing.body, body)
                merged_sources = sorted(set(sources) | set(meta.get("sources") or []))
                merged_supersedes = sorted(set(supersedes or [])
                                           | set(meta.get("supersedes") or []))
            meta.update({
                "slug": slug, "title": " ".join(title.split()), "kind": kind,
                "created": meta.get("created", today), "updated": meta.get("updated", today),
                "sources": merged_sources, "supersedes": merged_supersedes or [],
            })
            new_body = result.body.strip() + "\n"
            # Render with the PRIOR `updated` first and compare against the file as
            # read under this same lock. Byte-identical means nothing changed, so
            # nothing is written — a rewrite that changes nothing must not look
            # different from the page already on disk, or a no-op re-run bumps the
            # date, creates a commit, and later "refreshes" a page that the later
            # staleness check should instead have flagged.
            candidate = render_frontmatter(meta) + new_body
            if existing_text is not None and candidate == existing_text:
                last_unchanged = True
                return path
            meta["updated"] = today
            atomic_write(path, render_frontmatter(meta) + new_body)
            if lock.held:
                return path

        # Unlocked. Re-read outside the lock context and confirm nothing overwrote us
        # in the gap. On the last attempt keep what we wrote rather than looping for
        # ever: a page that may have lost a section still beats no page at all.
        if attempt == UNLOCKED_RETRIES - 1:
            return path
        try:
            written = path.read_text(encoding="utf-8")
        except OSError:
            return path
        if all(header in written for header in wanted):
            return path

    return path


def stamp_superseded(store: Path, slug: str, by_slug: str) -> None:
    """Mark the page a new decision replaces, on the page itself.

    The reversal has to be legible from the page that was reversed, not only from
    the one that reversed it: search ranks pages independently, and an agent that
    finds the old page has to be told it is old.
    """
    path = store / f"{slug}.md"
    with page_lock(path):
        page = parse_page(path)
        meta = dict(page.meta)
        meta.update({"slug": page.slug, "title": page.title, "status": "superseded",
                     "superseded_by": by_slug, "updated": _dt.date.today().isoformat()})
        atomic_write(path, render_frontmatter(meta) + page.body.strip() + "\n")


def reject(store: Path, code: str, reason: str, repair: str, slug: str = "") -> int:
    """Refuse the write and record why. Never writes a page.

    `code` is a short stable token rather than prose so refusals can be counted:
    a gate that fires constantly on one code is either a real corpus problem or
    a rule that needs loosening, and you cannot tell which from memory.
    """
    print(f"REJECTED: {reason}", file=sys.stderr)
    print(f"FIX: {repair}", file=sys.stderr)
    log_event(store, "reject", create=True, code=code, slug=slug, reason=reason)
    return 1


def _supersedes_chain(store: Path, start: str, target: str, depth: int = 20) -> bool:
    """Whether following `superseded_by` from `start` reaches `target`.

    Without this, a page could be superseded by a page it had itself superseded.
    Every page in the loop then carries `status: superseded`, so the whole chain
    is demoted and marked obsolete and nothing in it is current.
    """
    seen = set()
    slug = start
    while slug and slug not in seen and depth > 0:
        if slug == target:
            return True
        seen.add(slug)
        path = store / f"{slug}.md"
        if not path.exists():
            return False
        try:
            slug = parse_page(path).superseded_by or ""
        except OSError:
            return False
        depth -= 1
    return False


def validate(slug: str, kind: str, sources: list[str], body: str, store: Path,
             supersedes: list[str], resulting_body: str, title: str) -> int | None:
    """Return an exit code to refuse the write, or None to let it through."""
    problem = store_problem(store)
    if problem:
        return reject(
            store, "store_unusable", problem,
            "point --store or $PAGELORE_DIR at a directory, or restore the "
            "symlink target, then retry", slug)

    if not SLUG_RE.match(slug):
        return reject(
            store, "bad_slug",
            f"slug {slug!r} is not kebab-case (lowercase letters, digits, single hyphens)",
            "retry with a slug like 'pty-hangs-on-exit'", slug)

    if kind not in KINDS:
        return reject(
            store, "bad_kind",
            f"kind {kind!r} is not one of: {', '.join(KINDS)}",
            "pick the closest kind and retry", slug)

    if not sources:
        return reject(
            store, "no_sources",
            "no --source given; a page with no anchor in the codebase goes stale invisibly",
            f"retry with at least one: --source path/to/file (relative to {store.parent})",
            slug)

    missing = [s for s in sources if resolve_source(s, store) is None]
    if missing:
        return reject(
            store, "source_missing",
            f"these --source paths do not exist: {', '.join(missing)}",
            f"check the paths — they are resolved against {store.parent} and the "
            "working directory — then retry", slug)

    if slug in supersedes:
        return reject(
            store, "supersede_self",
            "--supersedes names the page being written; a page cannot replace itself",
            "drop --supersedes, or name the earlier page this one replaces", slug)

    absent = [s for s in supersedes if not (store / f"{s}.md").exists()]
    if absent:
        return reject(
            store, "supersede_missing",
            f"--supersedes names no page in this store: {', '.join(absent)}",
            "search for the page you mean and use its exact slug, or drop "
            "--supersedes if nothing is being replaced", slug)

    # Stamping walks through the path, so a page that is a symlink out of the
    # store would have its target read and copied into the store as a real file.
    # That turned --supersedes into the exfiltration primitive the read path had
    # just been fixed to close.
    root = store.resolve()
    unsafe = [s for s in supersedes if not is_page(store / f"{s}.md", root)]
    if unsafe:
        return reject(
            store, "supersede_unsafe",
            f"--supersedes names something that is not a page of this store: "
            f"{', '.join(unsafe)} (a symlink out of the store, or not a regular file)",
            "inspect that path by hand; the write path will not follow it", slug)

    # Follow `superseded_by` forward from the page being written: after this
    # write the target points at it, so a cycle exists exactly when the target is
    # already downstream of this page.
    cycle = [s for s in supersedes if _supersedes_chain(store, slug, s)]
    if cycle:
        return reject(
            store, "supersede_cycle",
            f"--supersedes would make a cycle: {', '.join(cycle)} is already "
            f"superseded, directly or transitively, by {slug!r}",
            "supersede the newest page in that chain, not one already replaced", slug)

    # Ahead of the length check: a page can be rewritten to be longer, but a
    # committed credential has to be pulled from history, so it is the more
    # urgent problem. `reason` names the kind and location only — never the
    # matched value — because `reason` is what `reject()` writes to the log.
    secrets = locate_secrets(title, body)
    if secrets:
        where = ", ".join(f"{kind} in {loc}" for kind, loc in secrets)
        return reject(
            store, "secret_in_body",
            f"the title or body looks like it contains a committed credential: {where}",
            "remove the value; name the environment variable or the secrets-store "
            "path instead",
            slug)

    if len(resulting_body.strip()) < MIN_BODY:
        return reject(
            store, "body_too_short",
            f"the page would be {len(resulting_body.strip())} characters, minimum is "
            f"{MIN_BODY} — a page this short restates what reading the source would "
            "already show",
            "write what a future agent could NOT reconstruct from the code (the cause "
            "behind the symptom, the alternative that was rejected and why), then retry",
            slug)

    return None


def main(argv: list[str] | None = None, *, prog: str = "lore write") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Write a project memory page.")
    add_version(ap)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--kind", default=None, help=f"one of: {', '.join(KINDS)}")
    ap.add_argument("--source", action="append", default=[],
                    help="file this page is about; repeatable; must exist")
    ap.add_argument("--supersedes", action="append", default=[], metavar="SLUG",
                    help="slug this page replaces; that page is marked superseded")
    ap.add_argument("--body", default=None, help="page body, or - to read stdin")
    ap.add_argument("--store", type=Path, default=None)
    args = ap.parse_args(argv)

    store = args.store or find_store()

    body = args.body
    if body == "-":
        body = sys.stdin.read()
    elif body is None:
        # There used to be a default body here reading "## Context / TODO: why
        # this matters." — a stub generator with a friendly face.
        return reject(
            store, "no_body",
            "no --body given",
            "pass --body with the text, or --body - to read it from stdin", args.slug)

    if not body.strip():
        # An empty body used to merge to a no-op: exit 0, nothing printed about
        # what changed, and `updated:` bumped on a page nobody touched.
        return reject(
            store, "no_body", "the body is empty",
            "pass the page text with --body, or --body - to read it from stdin",
            args.slug)

    if args.kind is None:
        return reject(
            store, "no_kind",
            f"no --kind given; one of: {', '.join(KINDS)}",
            "add --kind decision|bug|concept|howto and retry", args.slug)

    path = store / f"{args.slug}.md"
    existed = path.exists()
    # The floor applies to the page that will exist, so a short amendment to a
    # substantial page is allowed while a thin new page is not.
    try:
        result = merge(parse_page(path).body, body) if existed else MergeResult(body=body)
    except OSError:
        result = MergeResult(body=body)

    refusal = validate(args.slug, args.kind, args.source, body, store,
                       args.supersedes, result.body, args.title)
    if refusal is not None:
        return refusal

    # Entropy is checked on the same incoming title/body as locate_secrets, but
    # never blocks the write: it has false positives on legitimate long
    # tokens, so it is reported after the fact instead of refused up front.
    warn_locations = locate_high_entropy(args.title, body)
    warnings = ["high_entropy"] if warn_locations else []

    # Dangling links are checked against the RESULTING body — the page as it
    # will read after this write, not just the text this call typed — because
    # a merge can introduce or drop a `[[slug]]` that was in an earlier
    # section. A self-link is never dangling: the page being created here
    # cannot yet exist on disk to be found by the `store / f"{t}.md"` check
    # below, but it is not a broken reference. Not a refusal: an agent
    # legitimately writes page A linking to page B before B exists.
    # A target that is not itself a valid slug can never name a page in this
    # store, so it is reported dangling without ever touching the filesystem
    # — `[[../outside]]` or `[[/etc/hosts]]` must not be resolved as a path
    # relative to the store, the way `[[the-decision]].md` is. A target that
    # does look like a slug is "present" only through the same is_page()
    # guard --supersedes uses below: a symlink out of the store must not
    # count as the page it points at existing.
    root = store.resolve()
    dangling: list[str] = []
    seen_targets: set[str] = set()
    for target in links(result.body):
        if target == args.slug or target in seen_targets:
            continue
        seen_targets.add(target)
        if not SLUG_RE.match(target) or not is_page(store / f"{target}.md", root):
            dangling.append(target)
    if dangling:
        warnings.append("dangling_link")

    try:
        path = write_page(store, args.slug, args.title, args.kind,
                          args.source, body, args.supersedes)
        for slug in args.supersedes:
            stamp_superseded(store, slug, args.slug)
    except StoreUnavailable as exc:
        return reject(store, "store_unusable", str(exc),
                      "point --store at a usable directory and retry", args.slug)
    except OSError as exc:
        # A read-only or full store must produce a refusal, not a traceback: the
        # agent has to be able to tell "this page is bad" from "this disk is".
        return reject(store, "store_unwritable", f"cannot write to {store}: {exc}",
                      "check permissions and free space on that path, then retry",
                      args.slug)

    # write_page is the single authority on this: it decided under its own
    # lock, against the file as read under that lock. A second before/after
    # read here raced it — under a concurrent writer between the two reads, a
    # call that write_page genuinely skipped could still be reported as a
    # merge, or vice versa.
    unchanged = last_unchanged

    log_event(store, "write", create=True, slug=args.slug, kind=args.kind,
              mode="unchanged" if unchanged else ("merge" if existed else "create"),
              chars=len(body.strip()),
              replaced=result.replaced, supersedes=args.supersedes,
              **({"warnings": warnings} if warnings else {}))
    if unchanged:
        print("unchanged: nothing to write", file=sys.stderr)
    else:
        for header in result.replaced:
            print(f"replaced: {header}", file=sys.stderr)
        for header in result.appended:
            print(f"appended: {header}", file=sys.stderr)
    for slug in args.supersedes:
        print(f"superseded: {slug}", file=sys.stderr)
    for loc in warn_locations:
        print(f"⚠ {loc} looks like a credential (high-entropy string) — "
              "if it is one, remove it and rewrite the page", file=sys.stderr)
    for target in dangling:
        print(f"⚠ [[{target}]] names no page in this store — write it, or fix the slug",
              file=sys.stderr)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
