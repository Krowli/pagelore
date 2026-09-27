"""`lore show <slug>` — print one page, the one a search result named.

The contract used to say `cat <store>/<slug>.md`. It was correct and it was not
typed: the store path is absolute and appears once, on the first line of a search
result, so opening a page meant copying it out. `show` takes the slug the search
printed and nothing else. It prints the file verbatim, frontmatter included, because
the frontmatter is where a page says what it supersedes and what it is about.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import freshness
from .cli import add_version
from .lib import find_page, find_store, links, load_pages, read_text, refuse_missing


def main(argv: list[str] | None = None, *, prog: str = "lore show") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Print one page of project memory.")
    add_version(ap)
    ap.add_argument("slug", help="as a search result printed it")
    ap.add_argument("--store", type=Path, default=None)
    args = ap.parse_args(argv)
    store = args.store or find_store()
    cmd = prog.split()[0]

    page = find_page(store, args.slug)
    if page is None:
        return refuse_missing(store, args.slug, cmd)
    if page.superseded_by:
        # Search lifts the replacement above this page; asked for by name, the
        # page has to say it on its own, and on stderr so the page itself is clean.
        print(f"\u26a0 superseded by {page.superseded_by} \u2014 read that first: "
              f"{cmd} show {page.superseded_by}", file=sys.stderr)
    # Backlinks, not the page's own forward links: an agent that opens a page
    # can already see what it cites, the frontmatter and body are right there.
    # What it cannot see without reading every other page is who else already
    # points here \u2014 stdout stays byte-identical to the file, so this goes on
    # stderr alongside the superseded notice.
    backlinks = sorted({p.slug for p in load_pages(store)
                        if p.slug != page.slug and page.slug in links(p.body)})
    if backlinks:
        print(f"linked from: {', '.join(backlinks)}", file=sys.stderr)
    drifted = freshness.drift([page], store).get(page.slug)
    if drifted:
        if drifted.get("changed"):
            print(f"⚠ source changed: {', '.join(drifted['changed'])}", file=sys.stderr)
        if drifted.get("gone"):
            print(f"⚠ source gone: {', '.join(drifted['gone'])}", file=sys.stderr)
    sys.stdout.write(read_text(page.path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
