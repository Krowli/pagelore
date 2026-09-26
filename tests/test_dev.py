"""`lore dev` — the console, and the sandbox it runs in.

The console is a line editor, so most of it is drivable through a pipe: each test
runs the real subprocess (`python -m pagelore dev`) with lines on stdin and
asserts on stdout. One pty test proves what a pipe cannot — that a real terminal
gets the prompt and that typed commands run — and the sandbox tests prove the
property that matters most for a tool whose commands mutate things: that
`--sandbox` keeps every mutation inside a throwaway directory and HOME, so a
rehearsal can never touch the real store or a real config file.
"""
import os
import subprocess
import sys
from pathlib import Path

import conftest
import pytest

from pagelore import write as memory_write


def run_dev(argv, cwd, input_bytes, home=None) -> subprocess.CompletedProcess:
    """`lore dev <argv>` in a child, lines on stdin, everything else isolated."""
    env = {**os.environ, "PYTHONPATH": str(conftest.REPO / "src"),
           "PAGELORE_NO_REFRESH": "1"}
    if home:
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
    return subprocess.run([*conftest.LORE, *argv], cwd=cwd, input=input_bytes,
                          capture_output=True, env=env)


def _page(store: Path, slug: str) -> None:
    memory_write.write_page(
        store, slug, f"{slug} page", "bug", ["src/terminal/renderer.ts"],
        "## Cause\n\nThe renderer loses its context when the display sleeps."
        + conftest.FILLER)


@pytest.fixture()
def project(tmp_path):
    """A project with one real store, already holding one page."""
    project = tmp_path / "project"
    (project / ".memory").mkdir(parents=True)
    _page(project / ".memory", "webgl-context-loss")
    return project


def test_the_console_runs_a_command_and_answers(project):
    proc = run_dev(["dev"], project, b"search webgl context loss\nexit\n")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    text = proc.stdout.decode("utf-8", "replace")
    assert "lore dev" in text, text[:300]
    assert "webgl-context-loss" in text, text[-600:]


def test_eof_ends_the_console(project):
    proc = run_dev(["dev"], project, b"")
    assert proc.returncode == 0
    assert "lore dev" in proc.stdout.decode("utf-8", "replace")


def test_a_failing_command_prints_its_exit_code(project):
    proc = run_dev(["dev"], project, b"nonsense\nexit\n")
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8", "replace")
    assert "unknown command" in text
    assert "exit 2" in text


def test_quit_and_help(project):
    proc = run_dev(["dev"], project, b"help\nquit\n")
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8", "replace")
    assert "every line is one command" in text


def test_panes_falls_back_to_the_line_editor_without_a_tty(project):
    """`--panes` is a screen, not a gate: piped in, it says so and the console
    still reads lines — an agent that drives `lore dev` must not lose it."""
    proc = run_dev(["dev", "--panes"], project, b"help\nexit\n")
    assert proc.returncode == 0
    text = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    assert "the panes screen needs a real terminal" in text
    assert "every line is one command" in text, "the line editor still ran"


def test_sandbox_never_touches_the_real_store_or_home(tmp_path):
    project = tmp_path / "project"
    (project / ".memory").mkdir(parents=True)
    _page(project / ".memory", "keep-me")
    home = tmp_path / "home"
    home.mkdir()

    lines = [
        "init --scope global --agent claude --via file --yes",  # writes the block to the fake HOME
        "init --scope project --agent claude --via mcp --yes",  # registers MCP in the sandbox project
        "stats",                                              # reads the sandbox store
        'search "webgl context loss"',                        # empty there, and no error
        "uninstall",                                          # takes the registrations out
        "exit",
    ]
    proc = run_dev(["dev", "--sandbox"], project, ("\n".join(lines) + "\n").encode(),
                   home=home)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    text = proc.stdout.decode("utf-8", "replace")
    assert "sandbox" in text and "discarding the sandbox" in text, text[-600:]

    # Nothing the console ran landed in the real project store...
    assert (project / ".memory" / "keep-me.md").exists()
    assert not [p for p in (project / ".memory").iterdir()
                if p.name not in ("keep-me.md", "search.sqlite3")]
    assert not (project / ".mcp.json").exists()
    # ...and every child got a sandboxed HOME: the console's own HOME never grew
    # a .claude, so a machine's real one cannot either. The only trace that init
    # ran the file route is its own output, already asserted above.
    assert "wrote" in text
    assert not (home / ".claude").exists()


@conftest.needs_posix
def test_a_real_terminal_gets_the_prompt_and_runs_typed_commands(project, tmp_path):
    """The pty is the one thing a pipe cannot be: a prompt that waits for a key.

    The console must be an interactive surface on a real terminal, not a program
    that guessed EOF because stdin was a pipe.
    """
    import pty
    import select
    import time

    home = tmp_path / "home"
    home.mkdir()

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        os.environ.update({"HOME": str(home), "USERPROFILE": str(home),
                           "PYTHONPATH": str(conftest.REPO / "src"),
                           "PAGELORE_NO_REFRESH": "1"})
        os.execv(sys.executable, [sys.executable, "-m", "pagelore", "dev"])

    seen = b""

    def wait_for(token: bytes, deadline: float = 30) -> bool:
        nonlocal seen
        end = time.time() + deadline
        while token not in seen:
            if time.time() > end:
                return False
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                return False
            if not chunk:
                return False
            seen += chunk
        return True

    try:
        assert wait_for(b"> "), f"no prompt ever appeared\n{seen[-400:]!r}"
        os.write(fd, b"search webgl context loss\r")
        assert wait_for(b"webgl-context-loss"), f"the search answered nothing\n{seen[-400:]!r}"
        os.write(fd, b"quit\r")
        deadline = time.time() + 30
        while time.time() < deadline:
            if select.select([fd], [], [], 0.2)[0]:
                try:
                    if not os.read(fd, 4096):
                        break
                except OSError:
                    break
    finally:
        os.close(fd)
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

    text = seen.decode("utf-8", "replace")
    assert "lore dev" in text, text[:300]
    assert "webgl-context-loss" in text, text[-600:]