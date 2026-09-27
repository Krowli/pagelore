"""`lore init` asks four questions, and the questions have to be tested.

The shell installer this replaces shipped a dead prompt: a question placed after
the value it was supposed to decide, so both answers led to the same place. It
passed review because the only test that could reach the prompts drove a pty, and
nobody wrote one for that branch.

So interactivity here is a parameter with `isatty()` as its default, and these
drive the interactive path directly. A test that merely pipes stdin would take the
non-interactive branch and prove exactly as little as piping into the old script
did. One pty test at the end proves the default wiring itself.
"""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import conftest
import pytest

from pagelore import doctor, init, instructions, uninstall, write

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def machine(tmp_path, monkeypatch):
    """A throwaway home with a git repo under foot, so both questions are live."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("# My rules\n\nDo not break things.\n",
                                                encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    # `Path.home()` reads HOME on POSIX and USERPROFILE on Windows, so faking only
    # HOME leaves the Windows runs pointed at the real home directory. `--store home`
    # then created `C:\Users\runneradmin\.pagelore` on a CI machine, which is
    # how this was found: the assertion below that the target sits under the fake home.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.setenv(instructions.HOME_ENV, str(home / ".pagelore"))
    monkeypatch.setenv(instructions.NO_REFRESH_ENV, "1")
    monkeypatch.chdir(project)
    # Codex's files follow CODEX_HOME; a developer's own must not leak in.
    monkeypatch.delenv("CODEX_HOME", raising=False)
    # The MCP route registers a server with `claude mcp add` / `codex mcp add` when
    # that program is on PATH — and on a developer's machine it is. A test that
    # reached that call with the real `which` would edit the real ~/.claude.json.
    # So nothing is on PATH here unless a test says otherwise.
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    return home, project


def run(answers: str, argv=None, interactive=True):
    out = io.StringIO()
    code = init.main(argv or [], stdin=io.StringIO(answers), stdout=out,
                     interactive=interactive)
    return code, out.getvalue()


def test_the_block_is_written_before_the_line_that_points_at_it(machine):
    """Order, not taste: an `@path` to a missing file produces no error in any
    harness. The agent silently loads nothing, which is the failure this whole
    design exists to avoid."""
    code, out = run("2\n5\n")
    assert code == 0
    assert instructions.block_path().is_file()
    assert str(instructions.block_path()) in out


def test_choosing_an_agent_shows_the_exact_change_and_asks_first(machine):
    home, _ = machine
    _, out = run("2\n1\n\ny\n1\n")
    assert "This will change:" in out
    assert init.short(home / ".claude" / "CLAUDE.md") in out
    assert f"@{instructions.block_path()}" in out

    written = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert written.startswith("# My rules\n\nDo not break things.\n"), "it ate the user's text"
    assert f"@{instructions.block_path()}" in written
    assert instructions.MARK_BEGIN in written


def test_declining_the_preview_writes_nothing_and_still_says_what_to_add(machine):
    home, _ = machine
    _, out = run("2\n1\n\nn\n1\n")
    assert "nothing written" in out
    assert "To connect an agent yourself" in out
    assert instructions.MARK_BEGIN not in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")


def test_the_default_answer_connects_nothing(machine):
    """Writing into someone's global agent configuration unasked is not a default
    anyone gets to choose for them."""
    home, _ = machine
    _, out = run("2\n\n\n")
    assert instructions.MARK_BEGIN not in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "To connect an agent yourself" in out


def test_running_it_twice_replaces_the_block_rather_than_stacking_one(machine):
    home, _ = machine
    run("2\n1\n\ny\n1\n")
    run("2\n1\n\ny\n1\n")
    written = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert written.count(instructions.MARK_BEGIN) == 1
    assert written.count(instructions.MARK_END) == 1


def test_codex_gets_the_text_because_it_cannot_include_a_file(machine):
    home, _ = machine
    run("2\n3\n\ny\n1\n")
    written = (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert "Before stating anything about this project" in written
    assert f"@{instructions.block_path()}" not in written


def test_the_private_store_creates_nothing(machine):
    """`ensure_store` already creates and shields the store at the first write, so
    a directory made here would be both redundant and a surprise inside someone's
    repository."""
    _, project = machine
    run("2\n5\n1\n")
    assert not (project / ".memory").exists()


def test_the_tracked_store_is_marked_before_the_first_write(machine):
    """`.tracked` has to exist before anything writes, or the store gitignores
    itself behind a user who asked for the opposite."""
    _, project = machine
    run("2\n5\n2\n")
    assert (project / ".memory" / ".tracked").is_file()
    gitignore = project / ".gitignore"
    if gitignore.exists():
        assert ".memory/" not in gitignore.read_text(encoding="utf-8")


def test_the_home_store_symlinks_out_of_the_repo_and_gitignores_the_link(machine):
    """The third store mode, and the one nothing covered. `lib.py` and `index.py`
    both carry comments about what it invites — a network filesystem, a dead symlink
    — so the mode they describe has to exist and work."""
    home, project = machine
    code, out = run("", argv=["--store", "home", "--yes"], interactive=False)
    assert code == 0

    link = project / ".memory"
    assert link.is_symlink(), "the store is a real directory, not a link out of the repo"
    target = link.resolve()
    assert home in target.parents, f"{target} is not under the fake home"
    assert instructions.home() in target.parents, \
        "the store home and the block home are computed in two places again"
    assert ".memory/" in (project / ".gitignore").read_text(encoding="utf-8")
    assert init.short(target) in out

    # The link has to be writable end to end, or the mode is decorative.
    (project / "src").mkdir()
    (project / "src" / "a.ts").write_text("export {}\n", encoding="utf-8")
    body = ("## Cause\n\n" + "Enough body to clear the two-hundred-character floor that the "
            "write gate applies, so that the page actually lands in the symlinked store "
            "rather than being refused long before it ever gets that far at all.\n")
    assert write.main(["--slug", "probe", "--title", "Probe", "--kind", "bug",
                       "--source", "src/a.ts", "--body", body]) == 0
    assert (target / "probe.md").is_file()


def test_this_project_only_writes_into_the_repository_and_not_the_home(machine):
    """The question that was missing. The wizard offered three files, all of them
    global, and the screen said "applies to every project" — which is a notice, not
    a choice. The first person to run it wanted one project and had no way to say
    so."""
    home, project = machine
    _, out = run("1\n1\n\ny\n1\n")          # this project, Claude Code, the file, yes, private

    local = project / "CLAUDE.md"
    assert local.is_file(), "nothing was written into the project"
    assert f"@{instructions.block_path()}" in local.read_text(encoding="utf-8")
    assert instructions.MARK_BEGIN not in (home / ".claude" / "CLAUDE.md").read_text(
        encoding="utf-8"), "it wrote globally after being told this project only"
    assert str(local) in out, "the preview named a file other than the one it wrote"


def test_the_flag_is_the_same_answer_as_the_question(machine):
    home, project = machine
    code, _ = run("", argv=["--scope", "project", "--agent", "claude", "--yes"],
                  interactive=False)
    assert code == 0
    assert (project / "CLAUDE.md").is_file()
    assert instructions.MARK_BEGIN not in (home / ".claude" / "CLAUDE.md").read_text(
        encoding="utf-8")


def test_project_scope_outside_a_repository_says_so_instead_of_guessing(tmp_path, monkeypatch):
    """`--scope project` with no project is a contradiction, and silently writing to
    the global file would be the worst of the three possible answers."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
    loose = tmp_path / "loose"
    loose.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv(instructions.HOME_ENV, str(home / ".pagelore"))
    monkeypatch.setenv(instructions.NO_REFRESH_ENV, "1")
    monkeypatch.chdir(loose)

    _, out = run("", argv=["--scope", "project", "--agent", "claude", "--yes"],
                 interactive=False)
    assert "needs a git repository" in out


def test_no_terminal_asks_nothing_stalls_never_and_still_writes_the_block(machine):
    home, project = machine
    code, out = run("", interactive=False)
    assert code == 0
    assert instructions.block_path().is_file()
    assert "No terminal to confirm on" in out
    assert instructions.MARK_BEGIN not in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (project / ".memory").exists()


def test_flags_are_the_confirmation_so_it_works_in_a_pipeline(machine):
    home, project = machine
    code, _ = run("", argv=["--agent", "claude", "--store", "tracked", "--yes"],
                  interactive=False)
    assert code == 0
    assert instructions.MARK_BEGIN in (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert (project / ".memory" / ".tracked").is_file()


def test_uninstall_takes_out_the_block_and_leaves_the_pages(machine, capsys):
    home, project = machine
    run("2\n1\n\ny\n2\n")
    (project / ".memory" / "a-page.md").write_text("---\nslug: a-page\n---\n\nkeep me\n",
                                                   encoding="utf-8")

    assert uninstall.main([]) == 0
    assert (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") == \
        "# My rules\n\nDo not break things.\n"
    assert (project / ".memory" / "a-page.md").read_text(encoding="utf-8") == \
        "---\nslug: a-page\n---\n\nkeep me\n"
    assert ".memory/" in capsys.readouterr().out


def test_uninstall_yes_keeps_a_home_store_and_removes_only_program_files(machine, capsys):
    """`--store home` puts a project's pages inside the same directory as the block.
    `--yes` used to `rmtree` that directory, pages and all, while its help said
    "not your pages"."""
    _, project = machine
    code, _ = run("", argv=["--store", "home", "--yes"], interactive=False)
    assert code == 0
    store = instructions.home() / project.name
    page = store / "a-page.md"
    page.write_text("---\nslug: a-page\n---\n\nkeep me\n", encoding="utf-8")
    assert instructions.block_path().is_file()
    assert (instructions.home() / instructions.STAMP).is_file()
    capsys.readouterr()

    assert uninstall.main(["--yes"]) == 0
    out = capsys.readouterr().out
    assert page.read_text(encoding="utf-8") == "---\nslug: a-page\n---\n\nkeep me\n"
    assert (project / ".memory" / "a-page.md").is_file(), "the project's link went dark"
    assert not instructions.block_path().exists()
    assert not (instructions.home() / instructions.STAMP).exists()
    assert instructions.home().is_dir()
    assert f"kept:      {store}" in out
    assert f"removed:   {instructions.home()}\n" not in out


def test_uninstall_yes_removes_the_home_once_it_is_empty(machine, capsys):
    run("2\n1\n\ny\n2\n")
    assert instructions.block_path().is_file()

    assert uninstall.main(["--yes"]) == 0
    assert not instructions.home().exists()
    assert f"removed:   {instructions.home()}" in capsys.readouterr().out


def test_uninstall_yes_keeps_a_file_it_does_not_know(machine, capsys):
    run("2\n1\n\ny\n2\n")
    notes = instructions.home() / "my-notes.txt"
    notes.write_text("mine\n", encoding="utf-8")

    assert uninstall.main(["--yes"]) == 0
    assert notes.read_text(encoding="utf-8") == "mine\n"
    assert not instructions.block_path().exists()
    assert f"kept:      {notes}" in capsys.readouterr().out


def test_uninstall_yes_removes_the_legacy_link_only_when_it_points_at_the_home(machine):
    run("2\n1\n\ny\n2\n")
    legacy = instructions.legacy_home()
    legacy.symlink_to(instructions.home(), target_is_directory=True)

    assert uninstall.main(["--yes"]) == 0
    assert not legacy.is_symlink() and not legacy.exists()


def test_uninstall_yes_leaves_a_legacy_link_pointing_elsewhere(machine):
    home, _ = machine
    run("2\n1\n\ny\n2\n")
    elsewhere = home / "elsewhere"
    elsewhere.mkdir()
    legacy = instructions.legacy_home()
    legacy.symlink_to(elsewhere, target_is_directory=True)

    assert uninstall.main(["--yes"]) == 0
    assert legacy.is_symlink()


def test_uninstall_yes_keeps_the_legacy_link_while_a_store_is_kept(machine):
    """A pre-0.6.0 `--store home` project links through `~/.project-memory/<name>`;
    while its pages are kept, so is the link that reaches them."""
    _, project = machine
    run("", argv=["--store", "home", "--yes"], interactive=False)
    (instructions.home() / project.name / "a-page.md").write_text(
        "---\nslug: a-page\n---\n\nkeep me\n", encoding="utf-8")
    legacy = instructions.legacy_home()
    legacy.symlink_to(instructions.home(), target_is_directory=True)

    assert uninstall.main(["--yes"]) == 0
    assert legacy.is_symlink() and (legacy / project.name / "a-page.md").is_file()


def test_uninstall_removes_our_mcp_entry_and_keeps_the_neighbours(machine, capsys):
    _, project = machine
    target = project / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    run("1\n1\n2\ny\n1\n")
    assert uninstall.main([]) == 0
    assert mcp_json(target) == {"mcpServers": {"other": {"command": "x"}}}
    assert "MCP server" in capsys.readouterr().out


def test_uninstall_deletes_an_mcp_json_that_only_we_wrote(machine):
    _, project = machine
    run("1\n1\n2\ny\n1\n")
    assert (project / ".mcp.json").is_file()
    assert uninstall.main([]) == 0
    assert not (project / ".mcp.json").exists(), "an empty .mcp.json was left in the repo"


def test_uninstall_never_deletes_gemini_settings(machine):
    """settings.json is Gemini's file; emptied of our entry it stays where it was."""
    home, project = machine
    (home / ".gemini").mkdir()
    (home / ".gemini" / "settings.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    run("2\n2\n2\ny\n1\n")
    run("1\n2\n2\ny\n1\n")
    assert uninstall.main([]) == 0
    assert mcp_json(home / ".gemini" / "settings.json") == {"theme": "dark"}
    assert mcp_json(project / ".gemini" / "settings.json") == {}
    assert (project / ".gemini" / "settings.json").is_file()


def test_uninstall_prints_the_harness_remove_command_it_cannot_run(machine, capsys):
    home, _ = machine
    claude_json = home / ".claude.json"
    claude_json.write_text(json.dumps({"mcpServers": {"pagelore": {"command": "lore"}}}),
                           encoding="utf-8")
    (home / ".codex").mkdir()
    config = home / ".codex" / "config.toml"
    config.write_text('[mcp_servers.pagelore]\ncommand = "lore"\n', encoding="utf-8")
    before = claude_json.read_bytes(), config.read_bytes()

    assert uninstall.main([]) == 0               # which → None: nothing to run it with
    out = capsys.readouterr().out
    assert "claude mcp remove --scope user pagelore" in out
    assert "codex mcp remove pagelore" in out
    assert (claude_json.read_bytes(), config.read_bytes()) == before, "it edited a file it must not"


def test_uninstall_runs_the_harness_remove_when_it_is_there(machine, monkeypatch):
    home, project = machine
    (home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"pagelore": {"command": "lore"}}}), encoding="utf-8")
    ran = []

    def fake_run(argv, *a, **k):
        ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(init, "_project_root", lambda: project)
    monkeypatch.setattr(init.subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/fake/claude" if name == "claude" else None)
    assert uninstall.main([]) == 0
    assert ran == [["/fake/claude", "mcp", "remove", "--scope", "user", "pagelore"]]


def test_doctor_calls_nothing_connected_a_fault(machine):
    """Measured, an agent with the block searches 15 of 15 times and one without it
    never does. "Installed but not connected" is therefore broken, not neutral."""
    before = {row["check"]: row for row in doctor.findings()}
    assert before["connected"]["ok"] is False
    assert "nothing tells any agent" in before["connected"]["detail"]

    run("2\n1\n\ny\n1\n")
    after = {row["check"]: row for row in doctor.findings()}
    assert after["connected"]["ok"] is True
    assert after["agent:claude"]["ok"] is True


def test_doctor_catches_an_include_pointing_at_a_file_that_is_gone(machine):
    """The silent failure: no harness errors on a missing `@path`, the agent just
    stops searching, and nobody connects that to whatever deleted the file."""
    run("2\n1\n\ny\n1\n")
    instructions.block_path().unlink()

    claude = {row["check"]: row for row in doctor.findings()}["agent:claude"]
    assert claude["ok"] is False
    assert "MISSING" in claude["detail"]


def test_files_are_shown_home_relative_and_the_line_written_is_shown_verbatim(machine):
    """Every path on the screen wrapped at full length and the list stopped being
    readable; `~/` is what a person would type back. The one exception is the
    include line itself, which is shown exactly as it will be written, because a
    preview that differs from the write is not a preview."""
    home, _ = machine
    _, out = run("2\n1\n\ny\n1\n")
    assert f"block at {init.short(instructions.block_path())}" in out
    assert init.short(home / ".claude" / "CLAUDE.md") in out
    assert str(home / ".claude" / "CLAUDE.md") not in out, "an absolute path leaked"
    assert f"+ @{instructions.block_path()}" in out


def test_the_store_question_keeps_the_project_path_out_of_its_title(machine):
    """The path was glued to the end of the question with three spaces, which read
    as part of the question. It is the note under it."""
    _, project = machine
    _, out = run("2\n5\n1\n")
    assert "memory pages live?\n" in out, "the title does not end its own line"
    assert str(project) in out


def test_what_was_done_is_reported_as_an_aligned_indented_list(machine):
    """The report lines came out at column zero between two menus, in the same
    weight as everything else. They are one indented block with one label column."""
    import re
    _, out = run("2\n1\n\ny\n1\n")
    # On this path nothing echoes the typed answer, so a report line can follow the
    # prompt on the same line; the block is measured from its own indent.
    rows = [m for m in (re.search(r"  (wrote|updated|store)( +)\S", line)
                        for line in out.splitlines()) if m]
    assert len(rows) == 2, out
    assert {len(m.group(1)) + len(m.group(2)) for m in rows} == {10}, \
        "the two report lines do not share a value column"


def test_doctor_counts_an_mcp_registration_as_connected(machine, monkeypatch):
    """An agent reached over MCP is connected; the fault is nothing at all."""
    _, project = machine
    run("1\n1\n2\ny\n1\n")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: sys.executable)
    monkeypatch.setattr(doctor, "_handshake", lambda argv: (True, "memory_search, memory_write"))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:claude"]["ok"] is True
    assert str(project / ".mcp.json") in rows["mcp:claude"]["detail"]
    assert rows["connected"]["ok"] is True
    assert rows["mcp:handshake"]["ok"] is True


def test_doctor_flags_an_mcp_entry_whose_command_is_not_on_path(machine):
    """The harness will run `lore mcp` from its own PATH; a name it cannot find is
    a server that never starts, and the harness reports that quietly if at all."""
    run("1\n1\n2\ny\n1\n")
    rows = {row["check"]: row for row in doctor.findings()}       # which → None here
    assert rows["mcp:claude"]["ok"] is False
    assert "not on PATH" in rows["mcp:claude"]["detail"]
    assert "mcp:handshake" not in rows, "no command to shake hands with"


def test_doctor_reports_a_server_that_does_not_answer(machine, monkeypatch):
    run("1\n1\n2\ny\n1\n")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: sys.executable)
    monkeypatch.setattr(doctor, "_handshake", lambda argv: (False, "boom"))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:handshake"]["ok"] is False
    assert "boom" in rows["mcp:handshake"]["detail"]


def test_doctor_flags_a_lore_on_path_that_is_not_this_install(machine, monkeypatch):
    """Two installs, and PATH picks the wrong one: `--version` says where each one
    lives, which is the only honest comparison — `which` cannot see through a pipx
    shim or an npm copy."""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/elsewhere/bin/lore")
    monkeypatch.setattr(doctor.subprocess, "run", lambda argv, *a, **k:
                        subprocess.CompletedProcess(
                            argv, 0, "pagelore 9.9.9 (lore, python 3,"
                                     " /elsewhere/install/pagelore)", ""))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["command"]["ok"] is False
    assert "different install" in rows["command"]["detail"]
    assert "/elsewhere/install/pagelore" in rows["command"]["detail"]


def test_doctor_reads_an_install_directory_with_parentheses(machine, monkeypatch):
    """A pipx install on Windows lives under `C:\\Program Files (x86)\\...`; the
    parse took the `)` of `(x86)` for the end of the line and saw no directory."""
    where = r"C:\Program Files (x86)\pipx\venvs\pagelore\Lib\site-packages\pagelore"
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/elsewhere/bin/lore")
    monkeypatch.setattr(doctor.subprocess, "run", lambda argv, *a, **k:
                        subprocess.CompletedProcess(
                            argv, 0, f"pagelore 9.9.9 (lore, python 3.13.15, {where})", ""))
    rows = {row["check"]: row for row in doctor.findings()}
    assert "prints no install directory" not in rows["command"]["detail"]
    assert where in rows["command"]["detail"]


def test_doctor_accepts_a_command_that_is_this_install(machine, monkeypatch):
    """The parse stays honest to the real version line, so the match probe is fed
    `version_line` itself — a drift in the format fails here, not in the field."""
    from pagelore.cli import version_line
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/same/bin/lore")
    monkeypatch.setattr(doctor.subprocess, "run", lambda argv, *a, **k:
                        subprocess.CompletedProcess(argv, 0, version_line("lore"), ""))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["command"]["ok"] is True
    assert "this install" in rows["command"]["detail"]


def test_doctor_flags_a_command_that_will_not_answer_version(machine, monkeypatch):
    """The old-build case of the trap: no `--version`, and the harness would still
    start that `lore` for the handshake and get whatever an old server says."""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/elsewhere/bin/lore")
    monkeypatch.setattr(doctor.subprocess, "run", lambda argv, *a, **k:
                        subprocess.CompletedProcess(
                            argv, 2, "", "usage: lore: error: unrecognized arguments:"
                                         " --version"))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["command"]["ok"] is False
    assert "does not answer --version" in rows["command"]["detail"]


def test_the_real_handshake_lists_the_two_tools(machine, monkeypatch):
    """`machine` is load-bearing here: its NO_REFRESH and PAGELORE_HOME reach
    the child, or the router's housekeeping after `lore mcp` exits would rewrite the
    developer's real ~/.pagelore/AGENT.md with this tree's text."""
    monkeypatch.setenv("PYTHONPATH", str(REPO / "src"))
    ok, detail = doctor._handshake([*conftest.LORE])
    assert ok is True, detail
    assert "memory_search" in detail and "memory_write" in detail


def test_the_handshake_fails_closed_on_a_command_that_is_not_a_server(machine):
    ok, detail = doctor._handshake([sys.executable, "-c", "print('hello')"])
    assert ok is False
    assert detail


def test_doctor_says_nothing_about_mcp_when_none_is_registered(machine):
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:claude"]["ok"] is None
    assert rows["mcp:gemini"]["ok"] is None
    assert rows["mcp:codex"]["ok"] is None
    assert "mcp:handshake" not in rows


def test_doctor_ignores_a_local_scope_entry_of_another_project_in_claude_json(machine):
    """~/.claude.json nests local-scope servers under each project's path. Those are
    someone else's; reporting one as this project's would send `lore uninstall`
    after an entry it never wrote."""
    home, _ = machine
    (home / ".claude.json").write_text(json.dumps({"projects": {"/elsewhere": {
        "mcpServers": {"pagelore": {"type": "stdio", "command": "lore"}}}}}),
        encoding="utf-8")
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:claude"]["ok"] is None


def test_doctor_reads_a_user_scope_entry_from_claude_json(machine, monkeypatch):
    home, _ = machine
    (home / ".claude.json").write_text(json.dumps({"mcpServers": {"pagelore": {
        "type": "stdio", "command": "lore", "args": ["mcp"]}}}), encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: sys.executable)
    monkeypatch.setattr(doctor, "_handshake", lambda argv: (True, ""))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:claude"]["ok"] is True
    assert ".claude.json" in rows["mcp:claude"]["detail"]


def test_doctor_reads_codex_config_toml_without_a_toml_parser(machine, monkeypatch):
    home, _ = machine
    (home / ".codex").mkdir()
    (home / ".codex" / "config.toml").write_text(
        'model = "x"\n\n[mcp_servers.pagelore]\ncommand = "lore"\nargs = ["mcp"]\n\n'
        '[mcp_servers.pagelore.env]\nA = "1"\n', encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: sys.executable)
    monkeypatch.setattr(doctor, "_handshake", lambda argv: (True, ""))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:codex"]["ok"] is True
    assert "config.toml" in rows["mcp:codex"]["detail"]


# --- The fourth question: how the agent reaches it -------------------------------
#
# Answers, in order: scope (1 this project, 2 every project), agent (1 Claude,
# 2 Gemini, 3 Codex, 4 Cursor, 5 none), via (1 file, 2 MCP, "1 2" both, empty = file),
# confirm, store.

MCP_ADD_CLAUDE = "claude mcp add --transport stdio --scope user pagelore -- lore mcp"


def mcp_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_mcp_for_claude_in_this_project_writes_mcp_json(machine):
    """The route measured at 0/15 on default settings is still the person's to
    choose; the file it writes is the one Claude Code documents for a project."""
    _, project = machine
    _, out = run("1\n1\n2\ny\n1\n")
    target = project / ".mcp.json"
    assert str(target) in out, "the preview did not name the file it wrote"
    assert mcp_json(target)["mcpServers"]["pagelore"] == \
        {"type": "stdio", "command": "lore", "args": ["mcp"]}
    local = project / "CLAUDE.md"
    assert not local.exists() or instructions.MARK_BEGIN not in local.read_text(encoding="utf-8")


def test_both_methods_write_both(machine):
    _, project = machine
    run("1\n1\n1 2\ny\n1\n")
    assert instructions.MARK_BEGIN in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert "pagelore" in mcp_json(project / ".mcp.json")["mcpServers"]


def test_an_empty_answer_keeps_the_instruction_file(machine):
    """Enter alone is the measured default, on the numbered path as on the keyboard."""
    _, project = machine
    run("1\n1\n\ny\n1\n")
    assert instructions.MARK_BEGIN in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (project / ".mcp.json").exists()


def test_mcp_json_merge_keeps_what_was_there_and_is_idempotent(machine):
    _, project = machine
    target = project / ".mcp.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "keep": 1}),
                      encoding="utf-8")
    _, out = run("1\n1\n2\ny\n1\n")
    doc = mcp_json(target)
    assert doc["keep"] == 1 and doc["mcpServers"]["other"] == {"command": "x"}
    assert doc["mcpServers"]["pagelore"]["args"] == ["mcp"]
    assert "  updated   " in out

    before = target.read_bytes()
    _, out = run("1\n1\n2\ny\n1\n")
    assert target.read_bytes() == before, "a second run changed the file"
    assert "  unchanged " in out


def test_mcp_json_that_is_not_json_is_left_alone(machine):
    """A config someone keeps with comments in it is theirs to edit; the wizard says
    what to add and touches nothing."""
    _, project = machine
    target = project / ".mcp.json"
    target.write_text("{ not json\n", encoding="utf-8")
    code, out = run("1\n1\n2\ny\n1\n")
    assert code == 0
    assert target.read_text(encoding="utf-8") == "{ not json\n"
    assert "  skipped   " in out
    assert "claude mcp add" in out


def test_gemini_project_scope_writes_settings_json_without_a_type_field(machine):
    """Gemini's stdio entry has no `type`; its schema does not know the field."""
    _, project = machine
    run("1\n2\n2\ny\n1\n")
    entry = mcp_json(project / ".gemini" / "settings.json")["mcpServers"]["pagelore"]
    assert entry == {"command": "lore", "args": ["mcp"]}


def test_gemini_global_scope_writes_the_home_settings(machine):
    home, _ = machine
    run("2\n2\n2\ny\n1\n")
    entry = mcp_json(home / ".gemini" / "settings.json")["mcpServers"]["pagelore"]
    assert entry["command"] == "lore"


def test_claude_global_scope_runs_the_harness_command_after_confirming(machine, monkeypatch):
    """~/.claude.json is Claude Code's own file and editing it by hand is not
    documented, so the user-scope entry goes through `claude mcp add` — and only
    after the person said yes to the preview that named the command."""
    _, project = machine
    ran = []

    def fake_run(argv, *a, **k):
        ran.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")
    # subprocess and shutil are one module each for the whole process: a faked `run`
    # would break the `git rev-parse` inside `_project_root`, so that is pinned too.
    monkeypatch.setattr(init, "_project_root", lambda: project)
    monkeypatch.setattr(init.subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/fake/claude" if name == "claude" else None)

    _, out = run("2\n1\n2\ny\n1\n")
    assert ran == [["/fake/claude", "mcp", "add", "--transport", "stdio", "--scope", "user",
                    "pagelore", "--", "lore", "mcp"]]
    assert "  added     " in out and "via claude mcp add" in out


def test_claude_global_scope_without_the_harness_prints_the_command(machine, monkeypatch):
    ran = []
    monkeypatch.setattr(init, "_project_root", lambda: machine[1])
    monkeypatch.setattr(init.subprocess, "run", lambda *a, **k: ran.append(a))
    _, out = run("2\n1\n2\ny\n1\n")
    assert MCP_ADD_CLAUDE in out
    assert ran == []


def test_a_failing_harness_command_is_reported_not_hidden(machine, monkeypatch):
    monkeypatch.setattr(init, "_project_root", lambda: machine[1])
    monkeypatch.setattr(init.subprocess, "run",
                        lambda argv, *a, **k: subprocess.CompletedProcess(argv, 1, "", "nope\n"))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: "/fake/claude" if name == "claude" else None)
    _, out = run("2\n1\n2\ny\n1\n")
    assert "  skipped   " in out and "nope" in out
    assert MCP_ADD_CLAUDE in out, "the person was not told what to run instead"


def test_codex_mcp_is_global_whatever_the_scope(machine):
    """Codex keeps MCP servers in ~/.codex/config.toml and nowhere else, so
    'this project only' has no file to write; the command is the answer."""
    _, project = machine
    _, out = run("", argv=["--scope", "project", "--agent", "codex", "--via", "mcp", "--yes"],
                 interactive=False)
    assert "codex mcp add pagelore -- lore mcp" in out
    assert not (project / ".mcp.json").exists()


def test_the_via_flag_is_the_same_answer_as_the_question(machine):
    _, project = machine
    _, out = run("", argv=["--scope", "project", "--agent", "claude", "--via", "mcp", "--yes"],
                 interactive=False)
    assert (project / ".mcp.json").is_file()
    local = project / "CLAUDE.md"
    assert not local.exists() or instructions.MARK_BEGIN not in local.read_text(encoding="utf-8")
    # The two notes are printed on the scripted path too: the approval prompt Claude
    # Code will show, and what MCP alone measured.
    assert "approve" in out
    assert "ENABLE_TOOL_SEARCH" in out


def test_via_defaults_to_the_file_for_scripts(machine):
    _, project = machine
    run("", argv=["--scope", "project", "--agent", "claude", "--yes"], interactive=False)
    assert instructions.MARK_BEGIN in (project / "CLAUDE.md").read_text(encoding="utf-8")
    assert not (project / ".mcp.json").exists()


def test_the_command_flag_reaches_the_mcp_entry(machine):
    _, project = machine
    run("", argv=["--scope", "project", "--agent", "claude", "--via", "mcp",
                  "--command", "pagelore", "--yes"], interactive=False)
    assert mcp_json(project / ".mcp.json")["mcpServers"]["pagelore"]["command"] == "pagelore"


def test_mcp_only_on_claude_code_says_what_was_measured(machine):
    _, out = run("1\n1\n2\ny\n1\n")
    assert "ENABLE_TOOL_SEARCH" in out
    _, out = run("1\n1\n1 2\ny\n1\n")
    assert "ENABLE_TOOL_SEARCH" not in out, "the caveat is for MCP alone"


def test_the_preview_names_the_mcp_target_and_the_command(machine):
    home, project = machine
    _, out = run("2\n1\n2\nn\n1\n")
    assert MCP_ADD_CLAUDE in out
    assert "nothing written" in out
    assert not (project / ".mcp.json").exists()
    assert not (home / ".gemini").exists()


def test_the_manual_text_names_the_mcp_commands(machine):
    _, out = run("2\n5\n")
    assert "claude mcp add" in out
    assert "gemini mcp add" in out
    assert "codex mcp add" in out


@conftest.needs_posix
def test_it_asks_with_arrow_keys_on_a_real_terminal(tmp_path):
    """Every test above drives the numbered path, because a StringIO is not a
    terminal. This one proves the half they cannot reach: that a real terminal gets
    the keyboard menu, that arrows move the cursor, and that the wizard does not
    stall waiting for a key it has already been sent."""
    import pty
    import select
    import time

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        os.environ.update({"HOME": str(home), "USERPROFILE": str(home),
                           "PYTHONPATH": str(REPO / "src"),
                           instructions.HOME_ENV: str(home / ".pagelore"),
                           instructions.NO_REFRESH_ENV: "1"})
        os.execv(sys.executable, [sys.executable, "-m", "pagelore", "init"])

    # Scope: arrow down to "Every project", enter. Agents: enter with nothing ticked,
    # which is the default and connects nobody. Store: enter, which is private.
    script = [(b"Every project", b"\x1b[B\r"),
              (b"Which agents", b"\r"),
              (b"memory pages live", b"\r")]
    seen, deadline = b"", time.time() + 30
    try:
        while script and time.time() < deadline:
            if select.select([fd], [], [], 0.2)[0]:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                seen += chunk
            expect, keys = script[0]
            if expect in seen:
                os.write(fd, keys)
                script.pop(0)
                time.sleep(0.15)
        while time.time() < deadline and b"take it all back out" not in seen:
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            seen += chunk
    except OSError:
        pass
    finally:
        os.close(fd)
        os.waitpid(pid, 0)

    text = seen.decode("utf-8", "replace")
    assert not script, f"the wizard never asked: {[e for e, _ in script]}\n{text[-600:]}"
    assert "\u276f" in text, "the keyboard menu never drew its cursor"
    assert "Choice (" not in text, "a real terminal was given the numbered prompt"
    assert "take it all back out" in text, f"the wizard did not finish\n{text[-600:]}"
    # Nothing was ticked, so nothing may have been written.
    assert instructions.MARK_BEGIN not in (home / ".claude" / "CLAUDE.md").read_text(
        encoding="utf-8") if (home / ".claude" / "CLAUDE.md").exists() else True


@conftest.needs_posix
def test_the_fourth_question_is_asked_with_arrows_on_a_real_terminal(tmp_path):
    """The test above ticks no agent, so the question about how the agent reaches the
    memory never appears in it. This one ticks Claude Code and proves the fourth
    question is drawn by the keyboard menu, then escapes it (the file, the default)
    and declines the preview so that nothing is written."""
    import pty
    import select
    import time

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(project)
        os.environ.update({"HOME": str(home), "USERPROFILE": str(home),
                           "PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin",
                           instructions.HOME_ENV: str(home / ".pagelore"),
                           instructions.NO_REFRESH_ENV: "1"})
        os.execv(sys.executable, [sys.executable, "-m", "pagelore", "init"])

    script = [(b"This project only", b"\r"),
              (b"Which agents", b" \r"),                  # tick Claude Code, confirm
              (b"How should the agent reach it?", b"\x1b"),  # escape: nothing = the file
              (b"Write it?", b"n"),
              (b"memory pages live", b"\r")]
    seen, deadline = b"", time.time() + 30
    try:
        while script and time.time() < deadline:
            if select.select([fd], [], [], 0.2)[0]:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                seen += chunk
            expect, keys = script[0]
            if expect in seen:
                os.write(fd, keys)
                script.pop(0)
                time.sleep(0.15)
        while time.time() < deadline and b"take it all back out" not in seen:
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            seen += chunk
    except OSError:
        pass
    finally:
        os.close(fd)
        os.waitpid(pid, 0)

    text = seen.decode("utf-8", "replace")
    assert not script, f"the wizard never asked: {[e for e, _ in script]}\n{text[-600:]}"
    assert "How should the agent reach it?" in text
    assert "MCP server" in text
    assert "Choice (" not in text, "a real terminal was given the numbered prompt"
    assert "nothing written" in text, f"the preview was not declined\n{text[-600:]}"
    assert not (project / ".mcp.json").exists()
    assert not (project / "CLAUDE.md").exists()


# --- Project scope is taken back out and checked, like the global files ------------

def test_uninstall_strips_the_block_from_every_project_file(machine):
    """`--scope project` writes into the repository; uninstall that only looked at
    the home files left those blocks behind, dangling once the block file went."""
    _, project = machine
    (project / "CLAUDE.md").write_text("# Team rules\n", encoding="utf-8")
    run("", argv=["--scope", "project", "--agent", "claude", "--agent", "gemini",
                  "--agent", "codex", "--yes"], interactive=False)
    for name in ("CLAUDE.md", "GEMINI.md", "AGENTS.md"):
        assert instructions.MARK_BEGIN in (project / name).read_text(encoding="utf-8")

    assert uninstall.main([]) == 0
    assert (project / "CLAUDE.md").read_text(encoding="utf-8") == "# Team rules\n"
    for name in ("GEMINI.md", "AGENTS.md"):
        assert instructions.MARK_BEGIN not in (project / name).read_text(encoding="utf-8")


def test_doctor_counts_and_checks_a_project_scope_block(machine):
    _, project = machine
    run("", argv=["--scope", "project", "--agent", "claude", "--agent", "codex", "--yes"],
        interactive=False)
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["project:CLAUDE.md"]["ok"] is True
    assert rows["project:AGENTS.md"]["ok"] is True
    assert "Codex and Cursor" in rows["project:AGENTS.md"]["detail"]
    assert rows["connected"]["ok"] is True
    assert "project:GEMINI.md" not in rows, "a project file without our block is not a finding"

    instructions.block_path().unlink()
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    (project / "AGENTS.md").write_text(text.replace(f"pagelore {init.__version__}",
                                                    "pagelore 0.0.1"), encoding="utf-8")
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["project:CLAUDE.md"]["ok"] is False
    assert "MISSING" in rows["project:CLAUDE.md"]["detail"]
    assert rows["project:AGENTS.md"]["ok"] is False
    assert "STALE" in rows["project:AGENTS.md"]["detail"]


# --- CODEX_HOME moves the instruction file with the config ------------------------

def test_codex_home_moves_the_instruction_file_too(machine, monkeypatch, tmp_path):
    home, _ = machine
    elsewhere = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(elsewhere))
    run("", argv=["--agent", "codex", "--yes"], interactive=False)
    assert instructions.MARK_BEGIN in (elsewhere / "AGENTS.md").read_text(encoding="utf-8")
    assert not (home / ".codex" / "AGENTS.md").exists()

    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["agent:codex"]["ok"] is True
    assert str(elsewhere) in str(init.target_for("codex", None)[1])

    assert uninstall.main([]) == 0
    assert instructions.MARK_BEGIN not in (elsewhere / "AGENTS.md").read_text(encoding="utf-8")


# --- Cursor --------------------------------------------------------------------------

def test_cursor_mcp_in_this_project_writes_cursor_mcp_json(machine):
    _, project = machine
    run("", argv=["--scope", "project", "--agent", "cursor", "--via", "mcp", "--yes"],
        interactive=False)
    entry = mcp_json(project / ".cursor" / "mcp.json")["mcpServers"]["pagelore"]
    assert entry == {"type": "stdio", "command": "lore", "args": ["mcp"]}


def test_cursor_mcp_globally_writes_the_home_file(machine):
    home, _ = machine
    run("", argv=["--agent", "cursor", "--via", "mcp", "--yes"], interactive=False)
    assert "pagelore" in mcp_json(home / ".cursor" / "mcp.json")["mcpServers"]


def test_uninstall_takes_cursor_out_and_keeps_its_file(machine):
    home, project = machine
    (project / ".cursor").mkdir()
    (project / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    run("", argv=["--scope", "project", "--agent", "cursor", "--via", "mcp", "--yes"],
        interactive=False)
    run("", argv=["--agent", "cursor", "--via", "mcp", "--yes"], interactive=False)
    assert uninstall.main([]) == 0
    assert mcp_json(project / ".cursor" / "mcp.json") == {"mcpServers": {"other": {"command": "x"}}}
    assert mcp_json(home / ".cursor" / "mcp.json") == {}


def test_doctor_reads_a_cursor_registration(machine, monkeypatch):
    run("", argv=["--scope", "project", "--agent", "cursor", "--via", "mcp", "--yes"],
        interactive=False)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: sys.executable)
    monkeypatch.setattr(doctor, "_handshake", lambda argv: (True, ""))
    rows = {row["check"]: row for row in doctor.findings()}
    assert rows["mcp:cursor"]["ok"] is True
    assert ".cursor" in rows["mcp:cursor"]["detail"]


def test_cursor_file_route_uses_the_project_agents_md(machine):
    """Cursor reads a project's AGENTS.md, the same file Codex reads — written once."""
    _, project = machine
    _, out = run("", argv=["--scope", "project", "--agent", "codex", "--agent", "cursor",
                           "--yes"], interactive=False)
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count(instructions.MARK_BEGIN) == 1
    assert out.count("AGENTS.md") == 1


def test_cursor_globally_has_no_file_and_says_where_to_paste(machine):
    home, _ = machine
    _, out = run("", argv=["--agent", "cursor", "--yes"], interactive=False)
    assert "Customize → Rules" in out
    assert not (home / ".cursor").exists()


def test_the_project_agents_md_row_names_both_readers(machine):
    _, out = run("1\n5\n")
    assert "read by Codex and Cursor" in out
    assert "Cursor" in out


# --- Idempotence and --json ----------------------------------------------------------

def test_a_second_identical_run_reports_unchanged_and_writes_nothing(machine):
    home, _ = machine
    target = home / ".claude" / "CLAUDE.md"
    run("", argv=["--agent", "claude", "--yes"], interactive=False)
    stamp = target.stat().st_mtime_ns
    os.utime(target, ns=(stamp - 10**9, stamp - 10**9))
    _, out = run("", argv=["--agent", "claude", "--yes"], interactive=False)
    assert "  unchanged " in out
    assert target.stat().st_mtime_ns == stamp - 10**9, "an unchanged file was rewritten"


def test_json_puts_one_document_on_stdout_and_the_messages_on_stderr(machine, capsys):
    _, project = machine
    out = io.StringIO()
    code = init.main(["--agent", "claude", "--via", "file", "--via", "mcp", "--scope",
                      "project", "--json"], stdin=io.StringIO(""), stdout=out,
                     interactive=False)
    assert code == 0
    doc = json.loads(out.getvalue())
    assert doc["scope"] == "project" and doc["agents"] == ["claude"]
    assert doc["via"] == ["file", "mcp"]
    assert {c["action"] for c in doc["changes"]} >= {"wrote"}
    paths = {c["path"] for c in doc["changes"]}
    assert str(project / "CLAUDE.md") in paths and str(project / ".mcp.json") in paths
    assert "block at" in capsys.readouterr().err

    out = io.StringIO()
    init.main(["--agent", "claude", "--via", "file", "--via", "mcp", "--scope", "project",
               "--json"], stdin=io.StringIO(""), stdout=out, interactive=False)
    assert {c["action"] for c in json.loads(out.getvalue())["changes"]
            if c["path"]} == {"unchanged"}
