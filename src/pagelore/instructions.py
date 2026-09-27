"""The block an agent reads every turn: where it lives, and how it stays current.

Measured: with this block in the agent's instruction file, the agent searched the
store before answering 15 times out of 15 on a task-shaped prompt. Without it,
never. So where it lives and whether it is current is not a packaging detail — it
is the product working or not working.

It lives at `~/.pagelore/AGENT.md`, and the user's agent config carries one
line pointing there. Three properties follow, and each was chosen against an
alternative that fails silently:

- **One literal line**, identical on every machine and both install routes, which
  is what makes it get pasted correctly. A line into the installed package would
  read `…/python3.13/site-packages/…` and dangle after a Python upgrade — with no
  error, because a missing `@include` produces none. The agent simply stops
  searching, months later, and nobody connects the two events.
- **Refreshed by every invocation**, so an upgrade reaches the agent without the
  user editing anything. Pasting the contents into their config instead would
  freeze the block at install time, and refreshing *that* would mean rewriting a
  user's config unprompted.
- **Never created here.** The directory's existence is the opt-in signal. Same rule
  as `log_event`'s `create` flag: a read-only search must not dirty a machine that
  never asked for any of this.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import __version__
from .lib import atomic_write, env

HOME_ENV = "PAGELORE_HOME"
NO_REFRESH_ENV = "PAGELORE_NO_REFRESH"
HOME_DIRNAME = ".pagelore"
# Where the directory lived before 0.6.0, when the product still had two names.
# `migrate_home` moves it once and leaves a link behind; see there.
LEGACY_HOME_DIRNAME = ".project-memory"
STAMP = ".version"
BLOCK = "AGENT.md"
# Every project `lore init --scope project` connected, one absolute path per line.
# `uninstall` runs from one directory and has to reach all of them.
PROJECTS = "projects"

# Fences around what `lore init` writes into an agent's instruction file, so a
# second run replaces its own block instead of stacking another copy, and
# `lore uninstall` takes out exactly that and nothing a user wrote around it.
MARK_BEGIN = ("<!-- pagelore: managed by `lore init` — delete to the matching end "
              "marker to disconnect -->")
MARK_END = "<!-- pagelore: end -->"
# What `install.sh` wrote before 0.4.0, with its own end marker: a block left by the
# shell installer has to be matched byte for byte to be removed, and it is matched on
# the way in so that a user upgrading does not end up with two blocks, one of them
# pointing at a directory that is gone.
MARK_LEGACY = ("<!-- project-memory: installed by install.sh — delete to this file's "
               "matching end marker to disconnect -->")
MARK_LEGACY_END = "<!-- project-memory: end -->"

_BLOCK_RE = re.compile(re.escape(MARK_BEGIN) + r".*?" + re.escape(MARK_END) + r"\n?", re.S)
_LEGACY_RE = re.compile(re.escape(MARK_LEGACY) + r".*?" + re.escape(MARK_LEGACY_END) + r"\n?", re.S)


def home() -> Path:
    override = env(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / HOME_DIRNAME


def legacy_home() -> Path:
    return Path.home() / LEGACY_HOME_DIRNAME


def migrate_home(repoint=()) -> Path | None:
    """Move `~/.project-memory` to `~/.pagelore`, once. Returns the new path when it
    moved something, None otherwise. Never raises.

    One `rename`, so there is no moment with half a directory in each place. It is
    skipped when the home is set explicitly — the person chose that path — and when
    `~/.pagelore` already exists: two directories are not merged here, because one
    of them is someone's, and `lore doctor` names the pair instead.

    A link is left at the old path. `lore init --store home` points a project's
    `.memory` symlink into this directory, and those links are in repositories this
    process cannot enumerate; without the link, every such store would go dark on
    upgrade with no error. `repoint` names instruction files whose managed block
    includes the old path, and only that block is rewritten.
    """
    try:
        if env(HOME_ENV):
            return None
        old, new = legacy_home(), Path.home() / HOME_DIRNAME
        if old.is_symlink() or not old.is_dir() or new.exists() or new.is_symlink():
            return None
        os.rename(old, new)
    except OSError:
        return None
    try:
        old.symlink_to(new, target_is_directory=True)
    except OSError:
        pass            # Windows without the symlink privilege: the move still stands
    for path in repoint:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            continue
        new_text = _BLOCK_RE.sub(lambda m: m.group(0).replace(f"@{old}", f"@{new}"), text)
        if new_text != text:
            try:
                # `write_text`, not `atomic_write`: a CLAUDE.md is often a symlink into
                # someone's dotfiles, and a rename would replace the link with a copy.
                Path(path).write_text(new_text, encoding="utf-8")
            except OSError:
                pass
    return new


def block_path() -> Path:
    return home() / BLOCK


def packaged() -> str:
    return (Path(__file__).resolve().parent / "data" / BLOCK).read_text(encoding="utf-8")


# A line `<!-- mcp -->` or `<!-- mcp <tool> -->` in the packaged block marks the
# paragraph under it for the MCP server's `instructions`. Stripped from the file an
# agent reads; see `mcp_instructions`.
_MCP_MARK = re.compile(r"^<!-- mcp(?: (\w+))? -->\n", re.M)


def render(cmd: str = "lore") -> str:
    """The block as this install would write it.

    `str.replace` rather than `str.format`: the body is markdown that may grow a
    brace at any time, and a template that breaks on one is a worse trade than
    spelling the one substitution out.

    The command substitution is word-bounded, so `PMEOF` and `pagelore` are
    untouched — `pagelore` has no word boundary before its `lore`.
    """
    text = _MCP_MARK.sub("", packaged()).replace("{version}", __version__)
    return text if cmd == "lore" else re.sub(r"\blore\b", cmd, text)


def mcp_instructions(block: str | None = None) -> str:
    """What `lore mcp` sends in its initialize result: the marked paragraphs of the
    same block, so an agent with only the server connected is told what the file
    route tells it, and the two cannot drift.

    Not the whole block. That hands the agent shell commands a tool user has no use
    for, and it runs past 3k characters where a client puts this text in front of
    the model beside every other server's. A paragraph marked with a tool name ends
    in the colon that introduced the command; here it names the tool instead.
    """
    out = []
    for para in (packaged() if block is None else block).split("\n\n"):
        found = _MCP_MARK.match(para)
        if not found:
            continue
        text, tool = para[found.end():].strip(), found.group(1)
        if tool:
            text = text.rstrip(":") + f" with `{tool}`."
        out.append(text)
    return "\n\n".join(out)


def install(cmd: str = "lore") -> Path:
    """Create the directory and write the block. `lore init` only."""
    target = block_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, render(cmd))
    atomic_write(home() / STAMP, f"{__version__} {cmd}\n")
    return target


def installed_command() -> str:
    """The command name this machine was set up with, so a refresh does not rewrite
    a `pagelore` install back to `lore`."""
    try:
        parts = (home() / STAMP).read_text(encoding="utf-8").split()
    except OSError:
        return "lore"
    return parts[1] if len(parts) > 1 else "lore"


def refresh_quietly() -> bool:
    """Bring the block up to this install's text. Never raises, never creates.

    Compares rendered content rather than a version number, so a source checkout
    that edits the block without bumping the version also refreshes — the staleness
    class disappears instead of being narrowed. One small read and a string
    compare against a search that costs milliseconds.

    Writes through `atomic_write` because a fan-out of subagents will all reach
    this at once after an upgrade, and that is already the tested answer to two
    processes replacing one file.
    """
    try:
        if env(NO_REFRESH_ENV):
            return False
        if not home().is_dir():
            return False
        want = render(installed_command())
        target = block_path()
        try:
            if target.read_text(encoding="utf-8") == want:
                return False
        except OSError:
            pass
        atomic_write(target, want)
        atomic_write(home() / STAMP, f"{__version__} {installed_command()}\n")
        return True
    except Exception:
        # Housekeeping must never be the reason a search or a write fails.
        return False


def fenced(body: str) -> str:
    return f"{MARK_BEGIN}\n{body}\n{MARK_END}\n"


def replace_block(old: str, block: str) -> tuple[str, str]:
    """Fold the block into an instruction file. Returns (new text, what happened).

    A legacy `install.sh` block is removed first, so an upgrade replaces rather
    than duplicates. Everything the user wrote around the fence is untouched.
    "unchanged" means the text already carried exactly this block, and the caller
    need not write at all.
    """
    had_legacy = bool(_LEGACY_RE.search(old))
    original = old
    old = _LEGACY_RE.sub("", old)
    if _BLOCK_RE.search(old):
        new = _BLOCK_RE.sub(lambda _: block, old)
        return new, ("unchanged" if new == original else "updated")
    prefix = "" if (not old or old.endswith("\n")) else "\n"
    return old + prefix + ("\n" if old.strip() else "") + block, ("updated" if had_legacy else "wrote")


def strip_block(old: str) -> tuple[str, bool]:
    """Take our block back out, legacy included. Returns (new text, removed?)."""
    new = _LEGACY_RE.sub("", _BLOCK_RE.sub("", old))
    if new == old:
        return old, False
    return new.rstrip("\n") + "\n", True
