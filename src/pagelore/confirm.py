"""`lore confirm <slug>` — record that a page was checked against the code and holds.

`⚠ source changed` fires on any commit to a cited file, so in an active project it
soon sits on nearly every page (46 of 48 in this repository's own store on
2026-11-04) and stops telling anyone anything. The only way to clear it was to
change the page's text, which a page that is still right has no reason to do.
This stamps `checked:` — a UTC time — into the frontmatter; `freshness.drift`
compares sources against it, so only a source committed after the check marks the
page again. `updated` is left alone: the content did not change.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

from .cli import add_version
from .lib import (
    atomic_write,
    find_page,
    find_store,
    log_event,
    page_lock,
    parse_page,
    refuse_missing,
    resolve_source,
)
from .write import render_frontmatter


def stamp_checked(path: Path) -> str:
    """Write `checked: <now, UTC>` under the page lock; return the value written."""
    when = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    with page_lock(path):
        page = parse_page(path)
        meta = dict(page.meta)
        meta.update({"slug": page.slug, "title": page.title, "checked": when})
        atomic_write(path, render_frontmatter(meta) + page.body.strip() + "\n")
    return when


def main(argv: list[str] | None = None, *, prog: str = "lore confirm") -> int:
    ap = argparse.ArgumentParser(
        prog=prog, description="Record that a page was checked against the code and holds.")
    add_version(ap)
    ap.add_argument("slug", help="as a search result printed it")
    ap.add_argument("--store", type=Path, default=None)
    args = ap.parse_args(argv)
    store = args.store or find_store()
    cmd = prog.split()[0]

    page = find_page(store, args.slug)
    if page is None:
        return refuse_missing(store, args.slug, cmd)
    gone = [str(s) for s in page.meta.get("sources") or []
            if resolve_source(str(s), store) is None]
    if gone:
        # Not write.reject: that logs a refused *write*, which `lore stats` counts.
        print(f"REJECTED: source gone: {', '.join(gone)} — a page cannot be checked "
              "against a file that is not there", file=sys.stderr)
        print(f"FIX: {cmd} edit {page.slug}", file=sys.stderr)
        return 1
    when = stamp_checked(page.path)
    log_event(store, "confirm", slug=page.slug)
    print(f"confirmed  {page.path}  (checked {when})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
