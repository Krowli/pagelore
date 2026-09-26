"""`lore dev` — the same commands, in a console.

A bare `lore` opens this on a real terminal; `lore dev` opens it on demand, and
`--sandbox` runs it against a throwaway store so that `write`, `init`, `uninstall`
and the rest can be rehearsed against nothing that matters. Every line is one lore
command, run in its own child process from the current directory (or the sandbox),
so the exit codes, the output and the `FIX:` lines are exactly what an agent would
see in the same position. That is the whole point: the slow part of trying a new
build used to be installing it; the console makes the thing under test the one in
this tree, and a pipe is enough to drive it.

This is a line editor, not a menu: built on `input()` and the `readline` module
where Python ships it, with the chrome between commands printed rather than
redrawn on keypresses. So there is no raw mode and no cursor handling for a pty
test to race; what the pty test proves is the one thing a pipe cannot — that a
real terminal gets the prompt and that typed commands actually run.

The split is the same one `menu.py` draws for the wizard: a terminal gets the
interactive surface, and anything else — an agent, a script, a CI job — keeps the
plain behaviour, which is how a bare `lore` still answers a probe with usage and
exit 0.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import readline  # noqa: F401  # arrows and history, where Python ships it
except ImportError:
    pass  # Windows has no readline; input() still reads a line

from . import __version__
from .lib import STORE_DIRNAME, find_store

COMMANDS_HINT = "search show list write edit rm stats init doctor uninstall mcp version dev"
INTERNAL = ("help", "clear", "panes", "exit")


def console_here() -> bool:
    """Only a real terminal gets the console: an agent or a pipe sees usage text."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def dev_help(prog: str = "lore dev") -> str:
    return "\n".join([
        f"{prog} — pagelore {__version__}, the same commands in a console",
        "",
        f"every line is one command: {COMMANDS_HINT}",
        f"internal: {' · '.join(INTERNAL)}",
        "flags:    --sandbox  run against a throwaway store, discarded on exit",
        "          --panes    open the opencode-shaped screen: an ask box, a transcript of the commands it runs,",
        "                     / for the command picker, o to open the top hit, q back here",
        "write:    put a long body in quotes — `—body \"…\"`; the 200-character",
        "          floor still applies, and the refusal tells you so with a FIX: line",
    ])


def banner(store: Path, sandbox: Path | None, prog: str = "lore dev") -> str:
    """The chrome printed once at the top, and again after `clear`.

    Thin by design: lines, not widgets. What the commands print between prompts
    is the real surface, and it is exactly what an agent would see.
    """
    label = str(store)
    if len(label) > 46:
        label = "…" + label[-(46 - 1):]
    lines = [
        f"{prog} — pagelore {__version__}, the same commands in a console",
        f"store:   {label}",
    ]
    if sandbox is not None:
        lines += [
            f"         sandbox — {sandbox}, thrown away on exit",
        ]
    else:
        lines += [
            "         the nearest .memory upward, exactly as every command reads it",
        ]
    lines += [
        "type a lore command, or an internal one:",
        f"         {' · '.join(INTERNAL)}",
        "",
    ]
    return "\n".join(lines)


def run_line(line: str, cwd: Path, sandbox: Path | None, home: Path | None) -> None:
    """Run one line as `lore <line>` in a child, and print what it printed.

    A child rather than `cli.main` in-process so the console tests the command
    exactly as an agent calls it: real process, real exit code, real cwd. In a
    sandbox the child also gets a throwaway HOME, so `init` and `uninstall` can
    be rehearsed without touching a config anywhere on this machine.
    """
    argv = shlex.split(line)
    if not argv:
        return
    cmd = [sys.executable, "-m", "pagelore", *argv]
    env = os.environ.copy()
    if sandbox is not None:
        env["PAGELORE_DIR"] = str(sandbox / STORE_DIRNAME)
        if home is not None:
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True)
    except OSError as exc:
        print(f"could not run this line: {exc}")
        return
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace").rstrip("\n")
    if out:
        print(out)
    if proc.returncode:
        print(f"exit {proc.returncode}")
    print()


def _open_panes(store: Path, prog: str, cwd: Path,
                sandbox: Path | None, home: Path | None) -> None:
    """Open the opencode-shaped screen; `q` lands back here in the line editor.

    Bounded, because the screen never runs unless the terminal can host it — and
    the one thing it cannot do is change how a bare `lore` answers a probe. The
    sandbox plumbing follows the line editor's children: in-process commands from
    the field get the throwaway store, HOME and cwd too.
    """
    from . import panes
    try:
        panes.run_guarded(store, prog=f"{prog} --panes", cwd=cwd,
                          sandbox=sandbox, home=home)
    except KeyboardInterrupt:
        pass  # back to the line editor, which owns the ^C handling


def main(argv: list[str] | None = None, prog: str = "lore dev") -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    sandbox = False
    panes = False
    for a in argv:
        if a in ("-h", "--help"):
            print(dev_help(prog))
            return 0
        if a == "--sandbox":
            sandbox = True
        elif a == "--panes":
            panes = True
        else:
            print(f"lore dev: unknown option {a!r}", file=sys.stderr)
            return 2

    sandbox_dir: Path | None = None
    home: Path | None = None
    cwd = Path.cwd()
    if sandbox:
        sandbox_dir = Path(tempfile.mkdtemp(prefix="pagelore-sandbox-"))
        (sandbox_dir / STORE_DIRNAME).mkdir()
        (sandbox_dir / "src").mkdir()           # a source for a rehearsal write
        try:
            subprocess.run(["git", "init", "-q"], cwd=sandbox_dir, check=False)
        except OSError:
            pass
        home = sandbox_dir / "home"
        home.mkdir()
        cwd = sandbox_dir
        store = sandbox_dir / STORE_DIRNAME
    else:
        store = find_store()

    print(banner(store, sandbox_dir, prog))
    try:
        if panes:
            _open_panes(store, prog, cwd, sandbox_dir, home)
        while True:
            try:
                try:
                    line = input("> ")
                except EOFError:
                    print()
                    break
            except KeyboardInterrupt:
                print()
                continue
            line = line.strip()
            if not line:
                continue
            if line in ("exit", "quit", "q"):
                break
            if line in ("help", "?"):
                print(dev_help(prog))
                print()
                continue
            if line == "panes":
                _open_panes(store, prog, cwd, sandbox_dir, home)
                continue
            if line == "clear":
                print("\x1b[2J\x1b[H" if console_here() else "\n" * 2, end="")
                print(banner(store, sandbox_dir, prog))
                continue
            run_line(line, cwd, sandbox_dir, home)
    finally:
        if sandbox_dir is not None:
            print(f"discarding the sandbox at {sandbox_dir}")
            shutil.rmtree(sandbox_dir, ignore_errors=True)
    return 0