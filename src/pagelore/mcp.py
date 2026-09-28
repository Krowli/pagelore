"""`lore mcp` — the same memory, reached over MCP instead of by running a command.

    lore mcp            # speak MCP on stdin/stdout until stdin closes

Not a second implementation. Every call lands in the functions the CLI already
calls, so retrieval quality, the index and the write gate cannot differ between the
two routes — a page refused here is refused with the same reason and the same
`FIX:` line the command prints.

This was a probe in `evals/` for a month and measured before it shipped: on Claude
Code's default settings an agent with only these tools searched 0 times in 15,
because the harness defers MCP tools behind its tool search; with the deferral off,
or with the instruction file as well, 15 in 15 — equal to the instruction file
alone, never better. Re-measured on the day it shipped, on a later Claude Code, the
default arm was 3 in 5: no longer zero, not yet reliable. So the file stays the
default `lore init` recommends, and this is the choice a person makes with the
numbers in front of them. The probe stays as a wrapper so the measurement can be
re-run. Since 0.5.1 the initialize reply also carries `instructions`, the block's own
paragraphs on when to search and when to write; the same arm went from 4 in 10 to
10 in 10.

Two rules the transport imposes, both easy to break silently:

- stdout carries JSON-RPC messages, one per line, and nothing else. Every
  diagnostic goes to stderr. Messages are written as bytes so that a Windows text
  stream cannot turn the line ending into `\\r\\n`, and so that the router's
  `errors="replace"` never touches a payload.
- The store is not where the process happens to be standing. Claude Code makes no
  promise about a stdio server's working directory and puts the project root in
  `CLAUDE_PROJECT_DIR` instead; `resolve_store` reads that, after the explicit
  `PAGELORE_DIR`, before falling back to the cwd walk every command uses.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from . import __version__, instructions
from . import search as memory_search
from . import write as memory_write
from .cli import add_version
from .lib import STORE_ENV, env, find_store

PROTOCOL = "2025-06-18"
SERVER_NAME = "pagelore"
PROJECT_ENV = "CLAUDE_PROJECT_DIR"

# The text the model sees before it has called anything. It is the instruction
# block's own trigger, worded for a tool list rather than for a file: the two routes
# were compared on the promise that both say the same thing about when to use it,
# and changing these words means measuring again.
TOOLS = [
    {
        "name": "memory_search",
        "title": "Search project memory",
        "description": (
            "Search this project's durable memory: markdown pages recording decisions, "
            "rejected alternatives and the causes behind non-obvious bugs. Use before "
            "stating anything about this project — what it is, what it does, how a part "
            "works, why it is that way, what was decided or rejected — and before "
            "changing an unfamiliar subsystem. A hit marked 'superseded by' was replaced; "
            "read the replacement first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Every word you would try — synonyms, the "
                                         "component, the symptom — in one query; they "
                                         "are OR'd and ranked. Search again to ask "
                                         "something different, not to reword."},
                "touching": {"type": "array", "items": {"type": "string"},
                             "description": "Paths of files you are about to change: "
                                            "pages written against them come first. "
                                            "Pass it before editing a file."},
                "limit": {"type": "integer", "description": "Max results, default 10."},
            },
        },
    },
    {
        "name": "memory_write",
        "title": "Record a page in project memory",
        "description": (
            "Record what a future agent could not reconstruct from the code: the cause "
            "behind a symptom, the alternative that was rejected and why, a constraint "
            "from outside the repository. Use after an architectural decision, a "
            "non-obvious bugfix or a contract change; skip typos, reverts, formatting "
            "and test-only edits. Re-run the same slug to amend a page. A page that is "
            "not worth keeping is refused with the reason and the fix."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "kebab-case identifier."},
                "title": {"type": "string", "description": "One line."},
                "kind": {"type": "string", "enum": ["decision", "bug", "concept", "howto"]},
                "sources": {"type": "array", "items": {"type": "string"},
                            "description": "Files this page is about; each must exist."},
                "body": {"type": "string", "description": "Markdown, '## ' sections."},
                "supersedes": {"type": "array", "items": {"type": "string"},
                               "description": "Slugs this page replaces."},
            },
            "required": ["slug", "title", "kind", "sources", "body"],
        },
    },
]


def resolve_store() -> Path:
    """$PAGELORE_DIR, else the project the harness names, else the cwd walk.

    `main` resolves it once and says so on stderr, which is the one line a person
    debugging "it wrote the page somewhere else" needs; `handle` resolves it when it
    is handed none, so the protocol can be exercised without a server around it.
    A store that does not exist yet is still a path here — the first write creates it.
    """
    if env(STORE_ENV):
        return find_store()
    project = os.environ.get(PROJECT_ENV)
    return find_store(Path(project)) if project else find_store()


def do_search(args: dict, store: Path) -> tuple[str, bool]:
    query = args.get("query", "")
    hits = memory_search.search(query, store, k=int(args.get("limit", 10)),
                                touching=args.get("touching") or None, via="mcp")
    memory_search.annotate(hits, store)
    if not hits:
        return f"no matches in {store}", False
    lines = [f"{len(hits)} hit(s) in {store}"]
    lines += [memory_search.format_hit(s, p, query) for s, p in hits]
    if memory_search.last_skipped:
        lines.append(memory_search.format_skipped(memory_search.last_skipped, store))
    return "\n".join(lines), False


def do_write(args: dict, store: Path) -> tuple[str, bool]:
    """Straight through the command's own entry point, so the gate, the refusal
    codes and the `FIX:` lines are the ones the command produces rather than a
    second set that could drift from them. `--store` is passed explicitly: the
    command would otherwise walk up from the cwd, which is the one thing a stdio
    server must not trust — and sources resolve against the store's parent first,
    so the project's relative paths keep working from anywhere."""
    argv = ["--slug", str(args.get("slug", "")), "--title", str(args.get("title", "")),
            "--kind", str(args.get("kind", "")), "--body", str(args.get("body", "")),
            "--store", str(store)]
    for source in args.get("sources") or []:
        argv += ["--source", str(source)]
    for slug in args.get("supersedes") or []:
        argv += ["--supersedes", str(slug)]

    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = memory_write.main(argv)
    text = (out.getvalue() + err.getvalue()).strip()
    return text or ("written" if code == 0 else "refused"), code != 0


def handle(message: dict, store: Path | None = None) -> dict | None:
    """One request in, one reply out — or None for a notification."""
    method, mid = message.get("method"), message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            # The spec's "hint to the model", which a client MAY add to the system
            # prompt: the instruction block's own paragraphs, so an agent with only
            # this server connected is told when to search and when to write.
            "instructions": instructions.mcp_instructions(),
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        runner = {"memory_search": do_search, "memory_write": do_write}.get(name)
        if runner is None:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            text, failed = runner(args, store if store is not None else resolve_store())
        except Exception as exc:  # a crash must reach the model, not kill the server
            text, failed = f"{type(exc).__name__}: {exc}", True
        return {"jsonrpc": "2.0", "id": mid,
                "result": {"content": [{"type": "text", "text": text}], "isError": failed}}
    if mid is None:
        return None  # a notification carries no id and takes no answer
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main(argv: list[str] | None = None, *, prog: str = "lore mcp") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Serve the memory over MCP on stdio.")
    add_version(ap)
    ap.parse_args(argv)

    store = resolve_store()
    print(f"{prog}: serving {store}", file=sys.stderr)

    # Bytes when the stream has them, so that the newline is `\n` on every platform
    # and the router's `errors="replace"` reconfiguration never sees a payload.
    raw = getattr(sys.stdout, "buffer", None)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(message, store)
        if reply is None:
            continue
        data = json.dumps(reply, ensure_ascii=False) + "\n"
        if raw is not None:
            raw.write(data.encode("utf-8"))
            raw.flush()
        else:
            sys.stdout.write(data)
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
