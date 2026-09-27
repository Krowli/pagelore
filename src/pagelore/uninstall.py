"""`lore uninstall` — take the connection back out.

`pipx uninstall` removes the program and cannot run it, so it knows nothing about
the file this program edited in the user's agent configuration. Without this
command the fenced block survives as an `@include` pointing at a file nothing will
recreate — a dangling include, which produces no error and silently stops the
agent searching. That is the same failure the whole instruction-block design was
chosen to avoid, so leaving it to `pipx` is not an option.

It removes exactly what `lore init` wrote, and says what it deliberately did not:
the pages are the user's, and a program that can delete them by accident is worse
than no uninstaller.

The MCP route is taken out the way it went in: our entry is dropped from the JSON
files this program merged it into — and a `.mcp.json` that is empty afterwards is
deleted, because this program created it, while Gemini's settings.json and
Cursor's mcp.json are never deleted, because Gemini and Cursor write them too — and where the entry went through the harness's own
`mcp add`, its `mcp remove` is run when the harness is here and printed when not.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import init, instructions
from .cli import add_version
from .init import MCP_LEGACY, MCP_SERVER, PROJECT_FILES, agent_files, codex_home
from .lib import LOG_NAME, page_paths


def _remove_mcp(roots: list[Path], out) -> bool:
    """Take the MCP registration back out of every place `lore init` can put it.
    Returns True when anything was removed or a removal command was run or printed."""
    home = Path.home()
    did = False
    # The JSON files this program merges into. `.mcp.json` is ours to delete once it
    # is empty — nothing else writes it here — and settings.json never is.
    json_files = [path for root in roots
                  for path in (root / ".mcp.json", root / ".gemini" / "settings.json",
                               root / ".cursor" / "mcp.json")] \
        + [home / ".gemini" / "settings.json", home / ".cursor" / "mcp.json"]
    # Both names: the server was `project-memory` before 0.6.0.
    for path in json_files:
        for name in (MCP_SERVER, MCP_LEGACY):
            if not path.is_file():
                continue
            try:
                changed, empty = init.remove_json_server(path, name)
            except OSError as exc:
                print(f"skipped:   {path} ({exc})", file=sys.stderr)
                continue
            if not changed:
                continue
            did = True
            if empty and path.name == ".mcp.json":
                path.unlink()
                print(f"removed:   {path}  (only our MCP server was in it)", file=out)
            else:
                print(f"removed:   the MCP server {name} from {path}", file=out)
    # The files that went through the harness's own command go out the same way.
    for name in (MCP_SERVER, MCP_LEGACY):
        if init.registered_in_json(init._read_json(home / ".claude.json") or {}, name) is not None:
            init._run_or_print(init._remove_argv("claude", name), out, name)
            did = True
        if init.codex_registered(codex_home() / "config.toml", name) is not None:
            init._run_or_print(init._remove_argv("codex", name), out, name)
            did = True
    return did


# What this program writes into its home directory, and nothing else: the block, the
# version stamp, and the scratch copies `atomic_write` leaves if it dies mid-write.
# Everything else in there — above all a `lore init --store home` project store, which
# lives at `<home>/<project>/` — is someone's, and `uninstall` never deletes it.
_PROGRAM_FILES = (instructions.BLOCK, instructions.STAMP, instructions.PROJECTS)
_SCRATCH = re.compile(r"^\.(%s)\.\d+\.\d+\.tmp$"
                      % "|".join(re.escape(name) for name in _PROGRAM_FILES))


def _is_store(path: Path) -> bool:
    """A directory holding pages, or the log that only a store carries."""
    return path.is_dir() and (bool(page_paths(path)) or (path / LOG_NAME).is_file())


def _clean_home(home: Path, out) -> bool:
    """Remove the program's own files from `home`, and `home` itself if that empties
    it. Returns True when the directory is gone."""
    for entry in sorted(home.iterdir()):
        if entry.is_file() and not entry.is_symlink() and (
                entry.name in _PROGRAM_FILES or _SCRATCH.match(entry.name)):
            entry.unlink()
            print(f"removed:   {entry}", file=out)
    kept = sorted(home.iterdir())
    if not kept and not home.is_symlink():
        home.rmdir()
        print(f"removed:   {home}", file=out)
        return True
    stores = [entry for entry in kept if _is_store(entry)]
    for entry in stores:
        print(f"kept:      {entry}  (a --store home project store: your pages)", file=out)
    for entry in kept:
        if entry not in stores:
            print(f"kept:      {entry}  (not one of pagelore's own files)", file=out)
    print(f"kept:      {home}  (not empty; to delete what is left, pages included:"
          f" rm -r {home})", file=out)
    return False


def main(argv: list[str] | None = None, *, prog: str = "lore uninstall") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Disconnect the memory from your agents.")
    add_version(ap)
    ap.add_argument("--yes", action="store_true",
                    help="also remove pagelore's own files in ~/.pagelore/ (the block and "
                         "its version stamp), and the directory once it is empty; "
                         "--store home project stores in it are kept")
    args = ap.parse_args(argv)

    # Both scopes: the global files, and the project files of every repository
    # `lore init --scope project` connected — not only the one underfoot. A block
    # left in a project file dangles just like a global one once the block file is
    # gone, and uninstall runs from wherever the user happens to stand.
    roots = []
    for root in [init._project_root(), *init.remembered_projects()]:
        if root is None:
            continue
        if not root.is_dir():
            print(f"skipped:   {root}  (connected once, no longer exists)")
            continue
        roots.append(root.resolve())
    roots = list(dict.fromkeys(roots))
    targets = [target for _, target, _ in agent_files().values() if target is not None]
    targets += [root / name for root in roots for name in dict.fromkeys(PROJECT_FILES.values())]
    removed = False
    for target in dict.fromkeys(targets):
        if not target.is_file():
            continue
        try:
            old = target.read_text(encoding="utf-8")
            new, changed = instructions.strip_block(old)
            if changed:
                target.write_text(new, encoding="utf-8")
                print(f"removed:   the block in {target}")
                removed = True
        except OSError as exc:
            print(f"skipped:   {target} ({exc})", file=sys.stderr)

    removed = _remove_mcp(roots, sys.stdout) or removed
    removed = init.remove_legacy(roots, sys.stdout) or removed

    home = instructions.home()
    if args.yes and home.is_dir():
        gone = _clean_home(home, sys.stdout)
        removed = True
        # The link a 0.6.0 upgrade left at the old path. Only ours, and only once the
        # home is gone: a pre-0.6.0 `--store home` project reaches its kept pages
        # through it.
        legacy = instructions.legacy_home()
        if gone and legacy.is_symlink() and legacy.resolve() == home.resolve():
            legacy.unlink()
            print(f"removed:   {legacy}  (the link to the old location)")
    elif home.is_dir():
        print(f"kept:      {home}  (pass --yes to remove the block file in it too)")

    if not removed:
        print("nothing to remove: no block in any agent's instruction file, no MCP server "
              "registered")

    print("""
Left alone on purpose:
  .memory/ in your projects   your pages — delete a store yourself if you mean to
  anything you wrote yourself   a line you added by hand, or an agent definition

The program itself:  pipx uninstall pagelore   (or: npm uninstall -g pagelore)""")
    return 0
