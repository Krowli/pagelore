"""`lore doctor` — the detector for the three states that produce no error.

Every failure this reports is silent by nature, which is the whole reason it
exists:

- **A dangling include.** The agent config points at a block that is not there.
  Claude Code and Gemini resolve a missing `@path` to nothing and say nothing; the
  agent simply stops searching, and nobody connects that to whatever deleted the
  file months earlier.
- **A stale paste.** Codex and Cursor cannot include a file, so they carry a copy
  that no upgrade can reach. It keeps telling the agent to run a command that may
  have moved on.
- **Nothing connected at all.** Measured, an agent with the block searches 15 times
  out of 15 and an agent without it never does. So "installed but not connected" is
  a fault, not a neutral state, and this exits non-zero to say so.
- **An MCP entry the harness cannot start.** The config names a command; if that
  name is not on PATH the server never comes up, and a harness reports that quietly
  or not at all. And a server that starts must answer `tools/list` with the two
  tools — checked by running the very binary the config names, not this install.
- **A shadowing install.** The `lore` a harness starts is the one its PATH names,
  which may not be the one running this doctor; `--version` prints where each
  install lives, so the version probe *is* the comparison, and a binary that will
  not answer it is the old-build case of the same fault.

It also names the leftovers of the pre-0.4.0 layout, which nothing else will.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, instructions
from .cli import add_version
from .init import (
    MCP_LEGACY,
    MCP_SERVER,
    PROJECT_FILES,
    PROJECT_READERS,
    _project_root,
    _read_json,
    agent_files,
    codex_home,
    codex_registered,
    registered_in_json,
)
from .lib import find_store, page_paths

LEGACY_SKILL = Path.home() / ".agents" / "skills" / "project-memory"


def _mcp_registrations(root: Path | None,
                       name: str = MCP_SERVER) -> dict[str, tuple[Path, str | None]]:
    """Per agent: the file our server is registered in and the command it names.

    Read-only, and reading is fine where writing was not: ~/.claude.json and
    Codex's config.toml are looked at, never touched. `Path.home()` is read here
    rather than at import so a test can point it somewhere else.
    """
    home = Path.home()
    files = {
        "claude": ([root / ".mcp.json"] if root else []) + [home / ".claude.json"],
        "gemini": ([root / ".gemini" / "settings.json"] if root else [])
                  + [home / ".gemini" / "settings.json"],
        "cursor": ([root / ".cursor" / "mcp.json"] if root else [])
                  + [home / ".cursor" / "mcp.json"],
    }
    found: dict[str, tuple[Path, str | None]] = {}
    for key, candidates in files.items():
        for path in candidates:
            entry = registered_in_json(_read_json(path) or {}, name)
            if entry is not None:
                found[key] = (path, entry.get("command") or None)
                break
    config = codex_home() / "config.toml"
    command = codex_registered(config, name)
    if command is not None:
        found["codex"] = (config, command or None)
    return found


def _handshake(argv: list[str], timeout: float = 10) -> tuple[bool, str]:
    """Start `<argv> mcp`, send initialize and tools/list, expect the two tools.

    `argv` is the resolved command from the config, so this proves the server the
    harness will actually run — an old install earlier on PATH than this one fails
    here and says so. Every way this can go wrong comes back as (False, why); the
    doctor never raises.
    """
    feed = "\n".join(json.dumps(m) for m in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})) + "\n"
    try:
        proc = subprocess.run([*argv, "mcp"], input=feed, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return False, f"not a JSON-RPC line on stdout: {line[:80]!r}"
        if message.get("id") == 2:
            names = {t.get("name") for t in (message.get("result") or {}).get("tools", [])}
    if names == {"memory_search", "memory_write"}:
        return True, ", ".join(sorted(names))
    said = proc.stderr.strip().splitlines()
    why = said[0] if said else f"tools/list answered {sorted(n for n in names if n) or 'nothing'}"
    return False, (f"exit {proc.returncode}; " if proc.returncode else "") + why


def _same_install(command: str, here: str) -> tuple[bool, str]:
    """Is the `lore` on PATH this very install?

    The probe runs the binary it found, because only that binary can say where it
    lives: `--version` prints the source directory that install was built from.
    Comparing that with this file's directory catches a shadowing install that
    would otherwise sit silently earlier on PATH. A binary that will not answer,
    an old build with no `--version`, is itself the finding: a harness will start
    `lore mcp` from PATH anyway, and its handshake fails the way it did before
    this check existed.
    """
    try:
        proc = subprocess.run([command, "--version"], capture_output=True,
                              text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{command} will not answer --version ({type(exc).__name__})"
    if proc.returncode != 0:
        note = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = f"{command} does not answer --version"
        if note:
            detail += f": {note[0]}"
        return False, detail
    # The directory is everything after "python X.Y.Z, " — it may itself hold
    # parentheses, as `C:\Program Files (x86)\...` does on Windows.
    match = re.search(r", python [^,]+, (.+)\)$", (proc.stdout or "").strip())
    theirs = match.group(1) if match else None
    if theirs != here:
        theirs_note = theirs or "prints no install directory"
        return False, (f"{command} is a different install ({theirs_note}), not this one"
                       f" ({here}); a harness starts that one and its MCP handshake can"
                       " differ — put this install first on PATH")
    return True, f"{command} (this install: {here})"


def _block_finding(check: str, label: str, text: str, kind: str) -> dict:
    """What one instruction file that carries our block says: current, stale, or
    pointing at nothing. The same test at both scopes."""
    if instructions.MARK_LEGACY in text:
        return {"check": check, "ok": False,
                "detail": f"{label}: carries a pre-0.4.0 block — run `lore init` to replace it"}
    if kind == "paste":
        stamped = re.search(r"pagelore (\d+\.\d+\.\d+)", text)
        version = stamped.group(1) if stamped else None
        fresh = version == __version__
        return {"check": check, "ok": fresh,
                "detail": f"{label}: pasted copy of {version or 'an unknown version'}"
                          + ("" if fresh else f" — STALE, this install is {__version__};"
                                              " run `lore init` again")}
    pointed = re.search(r"^@(\S+)", text[text.find(instructions.MARK_BEGIN):], re.M)
    target_ok = bool(pointed) and Path(pointed.group(1)).is_file()
    # Still resolves through the link a 0.6.0 upgrade leaves at the old path, so it
    # is not a failure; it is one `lore init` away from not depending on the link.
    old = bool(pointed) and instructions.LEGACY_HOME_DIRNAME in Path(pointed.group(1)).parts
    return {"check": check, "ok": target_ok,
            "detail": f"{label}: includes {pointed.group(1) if pointed else '?'}"
                      + ("" if target_ok else " — that file is MISSING, the agent"
                                              " silently loads nothing; run `lore init`")
                      + (" — the pre-0.6.0 path; `lore init` points it at"
                         f" {instructions.block_path()}" if target_ok and old else "")}


def _home_findings() -> list[dict]:
    """A pre-0.6.0 `~/.project-memory` that was not moved. Every command moves it
    on its own, so one still here as a real directory means the move was refused:
    the new one already existed, and two directories are not merged by a program."""
    old, new = instructions.legacy_home(), instructions.home()
    if old.is_symlink() or not old.is_dir() or old == new:
        return []
    if new.exists():
        return [{"check": "home", "ok": False,
                 "detail": f"both {old} and {new} exist; {new} is the one in use. Move"
                           f" anything you still need out of {old}, then delete it"}]
    return [{"check": "home", "ok": False,
             "detail": f"{old} is the pre-0.6.0 location; `lore init` moves it to {new}"}]


def _has_block(text: str) -> bool:
    return instructions.MARK_BEGIN in text or instructions.MARK_LEGACY in text


def findings() -> list[dict]:
    out: list[dict] = []
    block = instructions.block_path()
    block_ok = block.is_file()
    out.append({"check": "block", "ok": block_ok, "detail": str(block) if block_ok
                else f"{block} is missing — run `lore init`"})

    connected = 0
    agents = agent_files()
    for key, (label, target, kind) in agents.items():
        if target is None:
            out.append({"check": f"agent:{key}", "ok": None,
                        "detail": f"{label}: global rules live in Customize → Rules, "
                                  "not a file; not checked"})
            continue
        if not target.is_file():
            out.append({"check": f"agent:{key}", "ok": None,
                        "detail": f"{label}: no {target}"})
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        if not _has_block(text):
            out.append({"check": f"agent:{key}", "ok": None,
                        "detail": f"{label}: not connected ({target})"})
            continue
        connected += 1
        out.append(_block_finding(f"agent:{key}", label, text, kind))

    # The project's own files, written by `lore init --scope project`. Reported only
    # when they carry our block: a repository without one is not a fault.
    root = _project_root()
    if root is not None:
        kinds = {name: agents[key][2] for key, name in PROJECT_FILES.items()}
        for name, kind in kinds.items():
            target = root / name
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not _has_block(text):
                continue
            connected += 1
            out.append(_block_finding(f"project:{name}", f"{PROJECT_READERS[name]} ({target})",
                                      text, kind))

    # The other route. An agent reached over MCP counts as connected; the fault this
    # detects is a registration the harness cannot start.
    registered = _mcp_registrations(root)
    shake: list[str] | None = None
    for key, (label, _, _) in agents.items():
        if key not in registered:
            out.append({"check": f"mcp:{key}", "ok": None,
                        "detail": f"{label}: not registered as an MCP server"})
            continue
        path, command = registered[key]
        where = f"{label}: MCP server in {path}"
        if command is None:
            connected += 1
            out.append({"check": f"mcp:{key}", "ok": True,
                        "detail": f"{where} (command not readable)"})
            continue
        exe = shutil.which(command)
        if exe is None:
            out.append({"check": f"mcp:{key}", "ok": False,
                        "detail": f"{where} → {command} mcp — but {command} is not on PATH;"
                                  " the harness cannot start it"})
            continue
        connected += 1
        shake = shake or [exe]
        out.append({"check": f"mcp:{key}", "ok": True, "detail": f"{where} → {command} mcp"})
    if shake is not None:
        ok, detail = _handshake(shake)
        out.append({"check": "mcp:handshake", "ok": ok,
                    "detail": f"{shake[0]} mcp answers tools/list with {detail}" if ok
                              else f"{shake[0]} mcp did not answer tools/list: {detail}"})

    # The pre-0.6.0 server name. It still starts, but `init` now registers `pagelore`,
    # and an agent given both gets every tool twice.
    for key, (path, _) in _mcp_registrations(root, MCP_LEGACY).items():
        out.append({"check": f"mcp-legacy:{key}", "ok": False,
                    "detail": f"{agents[key][0]}: MCP server still registered as"
                              f" `{MCP_LEGACY}` in {path} — `lore init --via mcp` replaces"
                              " the entry it wrote, `lore uninstall` removes it"})

    out.append({"check": "connected", "ok": connected > 0,
                "detail": f"{connected} agent(s) connected"
                          + ("" if connected else " — nothing tells any agent the memory exists")})

    store = find_store()
    pages = len(page_paths(store)) if store.is_dir() else 0
    out.append({"check": "store", "ok": True,
                "detail": f"{store}: {pages} page(s)" if store.is_dir()
                          else f"{store} does not exist yet; the first write creates it"})

    command = shutil.which("lore") or shutil.which("pagelore")
    here = str(Path(__file__).resolve().parent)
    if command is None:
        out.append({"check": "command", "ok": False,
                    "detail": "neither `lore` nor `pagelore` is on PATH"})
    else:
        ok, detail = _same_install(command, here)
        out.append({"check": "command", "ok": ok, "detail": detail})

    out.extend(_home_findings())

    if LEGACY_SKILL.exists():
        out.append({"check": "legacy", "ok": False,
                    "detail": f"{LEGACY_SKILL} is left over from the skill-directory layout"
                              " and is safe to delete"})
    return out


def main(argv: list[str] | None = None, *, prog: str = "lore doctor") -> int:
    ap = argparse.ArgumentParser(prog=prog, description="Check this install.")
    add_version(ap)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = findings()
    if args.json:
        print(json.dumps({"version": __version__, "findings": results},
                         ensure_ascii=False, indent=2))
    else:
        for row in results:
            mark = {True: "ok  ", False: "FAIL", None: "--  "}[row["ok"]]
            print(f"{mark}  {row['detail']}")
    failed = any(row["ok"] is False for row in results)
    if failed and not args.json:
        print("\nSomething above is broken in a way that produces no error on its own.",
              file=sys.stderr)
    return 1 if failed else 0
