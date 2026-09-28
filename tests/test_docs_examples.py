"""Every `lore …` line in the docs has to still be a command this build accepts.

Documentation drifts the moment a flag is renamed and nobody greps every `.md`
file for the old spelling. This walks every fenced code block in the docs a
person or an agent actually reads and, for each line that looks like an
invocation, checks that the subcommand's own `argparse` parser accepts it —
without running the command, so this stays fast and has no side effects.

Two shapes are deliberately not tested here:

- **Usage synopses** (`lore search [-k K] [--store STORE] …`), the bracket/brace
  grammar `docs/cli.md` prints under each command heading. That notation is not
  shell syntax — `[--store STORE]` is not a value the parser could accept — so
  these lines are named in `ALLOWLIST` with the reason, rather than pretended
  parseable.
- `lore dev`, which parses `--sandbox`/`--panes` by hand (see `dev.py`) rather
  than with `argparse`, so there is no parser to check it against; its one
  documented line is allowlisted for the same reason.
"""
from __future__ import annotations

import argparse
import importlib
import re
import shlex
from pathlib import Path

from pagelore.cli import COMMANDS, MODULES

REPO = Path(__file__).resolve().parents[1]

DOC_FILES = [REPO / "README.md", *sorted((REPO / "docs").glob("*.md")),
             REPO / "npm" / "README.md", REPO / "src" / "pagelore" / "data" / "AGENT.md"]

# file (relative to the repo root) -> {line: reason}. A line is skipped rather
# than parsed when it genuinely is not a command — usage grammar or prose — so a
# failure here always means a real documented invocation broke.
ALLOWLIST: dict[str, dict[int, str]] = {
    "docs/cli.md": {
        4: "two usage-synopsis fragments run together with prose (\"--help for one "
           "command's flags\"); not a literal invocation, and the apostrophe in "
           "\"command's\" is not shell-quoted",
        67: "usage synopsis: [--store STORE] is bracket grammar, not a real value",
        80: "usage synopsis: [--store STORE] is bracket grammar, not a real value",
        88: "usage synopsis: [--store STORE] [--since SINCE] [--json] is bracket grammar",
        118: "usage synopsis: [--kind KIND] [--source SOURCE] is bracket grammar",
        202: "usage synopsis: [--store STORE] is bracket grammar, not a real value",
        212: "usage synopsis: [--store STORE] is bracket grammar, not a real value",
        222: "usage synopsis: [--agent {...}] [--scope {...}] is bracket/choice grammar",
        265: "usage synopsis: [--json] is bracket grammar, not a real value",
        276: "usage synopsis: [--yes] is bracket grammar, not a real value",
        309: "usage synopsis, and lore dev parses --sandbox/--panes by hand — no "
             "argparse parser exists to check it against",
    },
}

# A bash heredoc opener: `<<'PMEOF'`, `<<PMEOF`, `<<-'PMEOF'`. Its body is page
# text, not a command, and is skipped up to the matching terminator line.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")

# Trailing shell syntax a documented command may carry that argparse never sees:
# a pipe into `grep`, a redirect, `2>&1`. Cut here rather than fed to the parser.
_CUT_TOKENS = {"|", ">", ">>", "2>&1", "<"}


def extract_commands(text: str) -> list[tuple[int, str]]:
    """(1-based line number, joined command text) for each `lore …` line found
    inside a fenced code block, backslash-continuations joined and heredoc
    bodies skipped."""
    lines = text.splitlines()
    in_fence = False
    i, n = 0, len(lines)
    found: list[tuple[int, str]] = []
    while i < n:
        stripped = lines[i].strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            i += 1
            continue
        if not in_fence:
            i += 1
            continue
        candidate = stripped[2:] if stripped.startswith("$ ") else stripped
        if not candidate.startswith("lore "):
            i += 1
            continue
        start_line = i + 1
        logical = candidate
        while logical.rstrip().endswith("\\"):
            i += 1
            logical = logical.rstrip()[:-1].rstrip() + " " + lines[i].strip()
        heredoc = _HEREDOC_RE.search(logical)
        if heredoc:
            marker = heredoc.group(2)
            logical = logical[:heredoc.start()].rstrip()
            i += 1
            while i < n and lines[i].strip() != marker:
                i += 1
        found.append((start_line, logical))
        i += 1
    return found


class _Parsed(Exception):
    """Raised the moment a subcommand's own `parse_args` returns, so the rest of
    its `main()` — the part that would actually write a page or serve MCP —
    never runs. Reaching this exception at all IS the assertion: it means
    `parse_args` accepted the argv without exiting."""


def _check_real_command(tokens: list[str]) -> tuple[bool, str]:
    """Whether `tokens` (argv, `tokens[0] == 'lore'`) is accepted by the CLI —
    either the top-level flags `cli.main` handles itself, or a subcommand's own
    `argparse` parser, exercised without running the command."""
    args = tokens[1:]
    if not args or args[0] in ("-h", "--help", "help", "-V", "--version", "version"):
        return True, ""  # handled by cli.main() itself, before any subcommand parser

    name, rest = args[0], args[1:]
    if name not in COMMANDS:
        return False, f"{name!r} is not a known command ({', '.join(COMMANDS)})"
    if name == "dev":
        # No argparse parser exists here at all (see module docstring) — a real
        # `lore dev …` line has to be verified by hand and added to ALLOWLIST.
        return False, "lore dev has no argparse parser to check against"

    module = importlib.import_module(f"pagelore.{MODULES.get(name, name)}")
    original = argparse.ArgumentParser.parse_args

    def intercept(self, args=None, namespace=None):
        original(self, args, namespace)
        raise _Parsed  # never return into the subcommand's own logic

    argparse.ArgumentParser.parse_args = intercept
    try:
        module.main(rest, prog=f"lore {name}")
        return False, "main() returned without ever calling parse_args"
    except _Parsed:
        return True, ""
    except SystemExit as exc:
        return False, f"parse_args exited ({exc.code}): argv was {rest!r}"
    finally:
        argparse.ArgumentParser.parse_args = original


def test_every_documented_lore_command_still_parses():
    failures: list[str] = []
    checked = 0
    for path in DOC_FILES:
        rel = path.relative_to(REPO).as_posix()
        reasons = ALLOWLIST.get(rel, {})
        for line_no, command in extract_commands(path.read_text(encoding="utf-8")):
            if line_no in reasons:
                continue
            try:
                tokens = shlex.split(command, comments=True)
            except ValueError as exc:
                failures.append(f"{rel}:{line_no}: could not be split as shell words "
                                 f"({exc}) — {command!r}")
                continue
            for idx, tok in enumerate(tokens):
                if tok in _CUT_TOKENS:
                    tokens = tokens[:idx]
                    break
            checked += 1
            ok, reason = _check_real_command(tokens)
            if not ok:
                failures.append(f"{rel}:{line_no}: {reason} — {' '.join(tokens)!r}")

    assert checked, "found no `lore …` example to check at all — extraction is broken"
    assert not failures, "stale documented example(s):\n" + "\n".join(failures)
